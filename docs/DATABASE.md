# DATABASE.md - Database design

This document explains the `wellbeing` database (MySQL 8): the tables, why each column has its data type, the keys, rules and indexes, the migrations, the roles, loading and cleaning the data, and the features, snapshots and query plans.

---

## 1. The tables

| Table | One row is | Purpose |
|---|---|---|
| `companies` | a client company | who the members work for |
| `members` | a member | the person (no name, email or phone number is stored) |
| `raw_daily_metrics` | one member's wearable data for one day, exactly as received | keeps bad readings for audit, so it has no range checks |
| `daily_metrics` | the same day, cleaned | has range checks; NULL when the wearable did not sync |
| `engagement` | one member's app use for one day | app opens, content views, challenge joined |
| `mood_checkins` | one mood check-in | only days where the member checked in |
| `member_features` | one member's calculated features for one date | averages, streaks and mood numbers, filled by the stored procedure `build_member_features` |
| `member_snapshots` | one member's summary for one date | the compact JSON summary that the insight service reads |
| `cleaning_log` | one line of the cleaning log | how many values were removed from each column in a run |

---

## 2. ER diagram

```mermaid
erDiagram
    companies ||--o{ members : "has (RESTRICT)"
    members ||--o{ raw_daily_metrics : "has (CASCADE)"
    members ||--o{ daily_metrics : "has (CASCADE)"
    members ||--o{ engagement : "has (CASCADE)"
    members ||--o{ mood_checkins : "has (CASCADE)"
    members ||--o{ member_snapshots : "has (CASCADE)"
    members ||--o{ member_features : "has (CASCADE)"

    companies {
        SMALLINT_UNSIGNED company_id PK
        VARCHAR name UK
        CHAR country
        DATE created_date
    }
    members {
        INT_UNSIGNED member_id PK
        CHAR member_code UK
        SMALLINT_UNSIGNED company_id FK
        ENUM age_band
        ENUM gender
        ENUM job_type
        DATE join_date
    }
    raw_daily_metrics {
        INT_UNSIGNED member_id PK_FK
        DATE metric_date PK
        INT steps
        INT active_minutes
        DECIMAL sleep_hours
        SMALLINT resting_hr
        TINYINT wearable_synced
        VARCHAR load_batch
    }
    daily_metrics {
        INT_UNSIGNED member_id PK_FK
        DATE metric_date PK
        SMALLINT_UNSIGNED steps
        SMALLINT_UNSIGNED active_minutes
        DECIMAL sleep_hours
        TINYINT_UNSIGNED resting_hr
        TINYINT wearable_synced
    }
    engagement {
        INT_UNSIGNED member_id PK_FK
        DATE activity_date PK
        SMALLINT_UNSIGNED app_opens
        SMALLINT_UNSIGNED content_views
        TINYINT challenge_joined
    }
    mood_checkins {
        INT_UNSIGNED member_id PK_FK
        DATE checkin_date PK
        TINYINT_UNSIGNED mood_score
    }
    member_snapshots {
        INT_UNSIGNED member_id PK_FK
        DATE as_of PK
        JSON snapshot
        DATETIME created_at
    }
    member_features {
        INT_UNSIGNED member_id PK_FK
        DATE as_of PK
        DECIMAL avg_steps_7d
        DECIMAL avg_steps_30d
        DECIMAL avg_active_7d
        DECIMAL avg_active_30d
        DECIMAL avg_sleep_7d
        DECIMAL avg_sleep_30d
        DECIMAL avg_hr_7d
        DECIMAL avg_hr_30d
        DECIMAL steps_change_pct
        DECIMAL active_change_pct
        DECIMAL sleep_change_pct
        DECIMAL hr_change_pct
        SMALLINT_UNSIGNED app_opens_7d
        SMALLINT_UNSIGNED app_opens_30d
        SMALLINT_UNSIGNED days_since_last_app_open
        SMALLINT_UNSIGNED app_streak
        SMALLINT_UNSIGNED active_streak
        DECIMAL sync_rate_30d
        JSON mood_last5
        TINYINT_UNSIGNED mood_low_count
    }
    cleaning_log {
        INT_UNSIGNED log_id PK
        CHAR run_id
        DATETIME run_at
        VARCHAR column_name
        VARCHAR rule_text
        INT_UNSIGNED values_received
        INT_UNSIGNED values_removed
    }
```

`companies` is the parent of `members`, and `members` is the parent of the data tables. `cleaning_log` is left alone with no relation.

---

## 3. Database settings

```sql
CREATE DATABASE IF NOT EXISTS wellbeing
  CHARACTER SET UTF8MB4
  COLLATE utf8mb4_0900_ai_ci;
```

Every table repeats the same engine, character set and collation, so nobody has to guess.

| Setting | Choice | Why |
|---|---|---|
| Storage engine | `InnoDB` | It supports transactions (changes succeed or fail together) and foreign keys. MyISAM supports neither. |
| Character set | `utf8mb4` | UTF8 for storing all characters including Arabic letters, English, and Emojis. MB4 (4 bytes) helps use Emojis as character. If we use MB3 and user inserts an emoji, their data might be lost. |
| Collation | `utf8mb4_0900_ai_ci` | utf8mb4 matching character set, 0900 Unicode 9, newest version that MySQL supports, ai for letters with marks such as in the french language or Arabic, ci for case-insensitivity. |

**Arabic text later.** `utf8mb4` stores Arabic correctly. With `ai` (accent-insensitive) a search ignores the small vowel marks (tashkeel), so a word written with and without them is found as the same word. In my tests on MySQL 8.0, letter variants such as the different forms of alef with hamza are still treated as different letters, and there is no Arabic-specific collation in this version, so a search that should treat those variants as equal would need the text normalised before it is stored.

---

## 4. Columns and data types

Quick guide to the sizes: `TINYINT` is 1 byte (unsigned 0 to 255), `SMALLINT` is 2 bytes (unsigned 0 to 65,535), `INT` is 4 bytes (unsigned 0 to about 4.29 billion). `UNSIGNED` means no negative numbers. The general rule is to use the smallest type that fits the valid range.

### companies

| Column | Type | NULL? | Why |
|---|---|---|---|
| `company_id` | `SMALLINT UNSIGNED`, auto-increment | NOT NULL | SMALLINT + UNSIGNED = 0-65,535 range, more than enough, auto_increment as it is the primary key and registers company_id, required (cannot be null) |
| `name` | `VARCHAR(100)` | NOT NULL | Names vary in length. 100 characters is enough |
| `country` | `CHAR(2)` | NOT NULL | A country code is always exactly 2 letters. AE, SA in our case. |
| `created_date` | `DATE` | NOT NULL | A calendar day, no timestamp needed. |

### members

| Column | Type | NULL? | Why |
|---|---|---|---|
| `member_id` | `INT UNSIGNED`, auto-increment | NOT NULL | Internal key used in every join. Members can exceed 65,535, so I chose `INT`. |
| `member_code` | `CHAR(6)` | NOT NULL | The member code the service sees, such as M0042, CHAR(6) leaves room for up to M99999 |
| `company_id` | `SMALLINT UNSIGNED` | NOT NULL | Must match `companies.company_id` exactly or the foreign key fails. |
| `age_band` | `ENUM(...)` | NOT NULL | A small fixed list. ENUM is used since the list doesn't change often, takes less size than check constraint using VARCHAR |
| `gender` | `ENUM('female','male','undisclosed')` | NOT NULL | Same reason |
| `job_type` | `ENUM('desk','field','shift')` | NOT NULL | Same Reason |
| `join_date` | `DATE` | NOT NULL | A calendar day, no timestamp needed. |

### raw_daily_metrics (wide, signed types so bad readings can still be stored)

| Column | Type | NULL? | Why |
|---|---|---|---|
| `member_id` | `INT UNSIGNED` | NOT NULL | Same type as `members.member_id`. |
| `metric_date` | `DATE` | NOT NULL | The member's local day. no timestamp needed. |
| `steps` | `INT` | NULL | Signed and wide so an impossible value like 150,000 is still kept. NULL if the wearable sent nothing. |
| `active_minutes` | `INT` | NULL | Same reason. |
| `sleep_hours` | `DECIMAL(5,2)` | NULL | Exact decimals, with room for wrong values like 23.5 or -1.5. |
| `resting_hr` | `SMALLINT` | NULL | Signed, so 0 or 220 bpm are kept. |
| `wearable_synced` | `TINYINT(1)` | NOT NULL | 1 = synced, 0 = not. It must always be known. |
| `load_batch` | `VARCHAR(32)`, default `'initial'` | NOT NULL | Added later by migration 003. It says which data load a row came from (for example `n500` or `n5000`). The default `'initial'` means rows that already existed were kept and labelled without losing anything. |

### daily_metrics (narrow, unsigned types because only valid values are allowed)

| Column | Type | NULL? | Why |
|---|---|---|---|
| `member_id` | `INT UNSIGNED` | NOT NULL | Same as the parent key. |
| `metric_date` | `DATE` | NOT NULL | The calendar day. |
| `steps` | `SMALLINT UNSIGNED` | NULL | The valid range 0 to 60,000 fits in 2 bytes. NULL means no valid value. |
| `active_minutes` | `SMALLINT UNSIGNED` | NULL | The range 0 to 600 does not fit `TINYINT` (maximum 255). |
| `sleep_hours` | `DECIMAL(3,1)` | NULL | Exact, one decimal such as 7.3. |
| `resting_hr` | `TINYINT UNSIGNED` | NULL | The range 30 to 120 fits in one byte. |
| `wearable_synced` | `TINYINT(1)` | NOT NULL | 1 = synced, 0 = not synced. |

### engagement

| Column | Type | NULL? | Why |
|---|---|---|---|
| `member_id` | `INT UNSIGNED` | NOT NULL | Same as the parent key. |
| `activity_date` | `DATE` | NOT NULL | The calendar day. |
| `app_opens` | `SMALLINT UNSIGNED`, default 0 | NOT NULL | More than 255 opens in a day is possible in theory, so not `TINYINT`. Zero is a real value, so default 0 instead of NULL. |
| `content_views` | `SMALLINT UNSIGNED`, default 0 | NOT NULL | Same reason. |
| `challenge_joined` | `TINYINT(1)`, default 0 | NOT NULL | A yes/no flag. 0 means did not join. |

### mood_checkins

| Column | Type | NULL? | Why |
|---|---|---|---|
| `member_id` | `INT UNSIGNED` | NOT NULL | Same as the parent key. |
| `checkin_date` | `DATE` | NOT NULL | The day of the check-in. |
| `mood_score` | `TINYINT UNSIGNED` | NOT NULL | Values 1 to 5 need one byte. A row exists only if a check-in happened, so it is never NULL. |

### member_snapshots

| Column | Type | NULL? | Why |
|---|---|---|---|
| `member_id` | `INT UNSIGNED` | NOT NULL | Same as the parent key. |
| `as_of` | `DATE` | NOT NULL | The date the snapshot describes. |
| `snapshot` | `JSON` | NOT NULL | MySQL checks that the text is valid JSON. |
| `created_at` | `DATETIME`, default current time | NOT NULL | Filled in automatically. `DATETIME` is used instead of `TIMESTAMP` because `TIMESTAMP` stops in 2038 and converts time zones. Stored in UTC. |

### member_features

One row per member per as-of date, filled by `build_member_features`. Values that cannot be calculated are NULL.

| Column | Type | NULL? | Why |
|---|---|---|---|
| `member_id` | `INT UNSIGNED` | NOT NULL | Same type as `members.member_id`. Together with `as_of` it is the primary key. |
| `as_of` | `DATE` | NOT NULL | The date the features are calculated for. |
| `avg_steps_7d`, `avg_steps_30d` | `DECIMAL(8,1)` | NULL | Averages are exact decimals with one decimal, like the source data. NULL means no valid value in that window. |
| `avg_active_7d`, `avg_active_30d` | `DECIMAL(6,1)` | NULL | Active minutes are at most 600. |
| `avg_sleep_7d`, `avg_sleep_30d` | `DECIMAL(4,1)` | NULL | Sleep is at most 14.0 hours. |
| `avg_hr_7d`, `avg_hr_30d` | `DECIMAL(5,1)` | NULL | Resting heart rate is at most 120. |
| `steps_change_pct`, `active_change_pct`, `sleep_change_pct`, `hr_change_pct` | `DECIMAL(7,1)` | NULL | A percent change can be negative, so it is signed. NULL when the 30-day average is missing or 0. |
| `app_opens_7d`, `app_opens_30d` | `SMALLINT UNSIGNED` | NOT NULL | A count, never negative. 30 days x 500 opens = 15,000 fits in 2 bytes. 0 when there are none. |
| `days_since_last_app_open` | `SMALLINT UNSIGNED` | NULL | NULL means the member never opened the app. |
| `app_streak`, `active_streak` | `SMALLINT UNSIGNED` | NOT NULL | Days in a row, never negative. 0 means no streak. |
| `sync_rate_30d` | `DECIMAL(4,3)` | NULL | A share from 0.000 to 1.000. |
| `mood_last5` | `JSON` | NOT NULL | A list of 0 to 5 scores, newest first. An empty list `[]` when the member has no check-ins. |
| `mood_low_count` | `TINYINT UNSIGNED` | NOT NULL | How many of those scores are 2 or below, 0 to 5. |

### cleaning_log

| Column | Type | NULL? | Why |
|---|---|---|---|
| `log_id` | `INT UNSIGNED`, auto-increment | NOT NULL | The database numbers each line. |
| `run_id` | `CHAR(36)` | NOT NULL | A UUID is always 36 characters. It groups the lines of one run. |
| `run_at` | `DATETIME` | NOT NULL | When the run started (UTC). |
| `column_name` | `VARCHAR(32)` | NOT NULL | Short names that vary in length. |
| `rule_text` | `VARCHAR(120)` | NOT NULL | A short sentence that varies in length. |
| `values_received` | `INT UNSIGNED` | NOT NULL | A count, never negative, and it can reach hundreds of thousands. |
| `values_removed` | `INT UNSIGNED` | NOT NULL | Same reason. |

---

## 5. Keys and rules

### Primary keys

| Table | Primary key | Meaning |
|---|---|---|
| `companies` | `company_id` | one row per company |
| `members` | `member_id` | one row per member |
| `raw_daily_metrics`, `daily_metrics` | `(member_id, metric_date)` | one row per member per day |
| `engagement` | `(member_id, activity_date)` | one row per member per day |
| `mood_checkins` | `(member_id, checkin_date)` | one check-in per member per day |
| `member_snapshots`, `member_features` | `(member_id, as_of)` | one row per member per date |
| `cleaning_log` | `log_id` | one log line |

### Unique keys

- `uq_companies_name`: no two companies share a name.
- `uq_members_code`: no two members share a code.

### CHECK constraints

| Constraint | Rule |
|---|---|
| `ck_companies_country` | country is `AE` or `SA` |
| `ck_dm_steps` | steps between 0 and 60,000 |
| `ck_dm_active` | active minutes between 0 and 600 |
| `ck_dm_sleep` | sleep between 2.0 and 14.0 hours |
| `ck_dm_hr` | resting heart rate between 30 and 120 |
| `ck_dm_synced` | if the wearable did not sync, all four metrics must be NULL |
| `ck_eng_opens`, `ck_eng_views` | at most 500 |
| `ck_eng_challenge` | `challenge_joined` is 0 or 1 |
| `ck_mood_score` | mood score between 1 and 5 |

A `CHECK` passes when the value is NULL, so the metric columns can still be NULL.

### Foreign keys (what happens when a parent row is deleted)

| Foreign key | Rule | Why |
|---|---|---|
| `members.company_id` to `companies` | `RESTRICT` | A company that still has members cannot be deleted by accident. |
| `member_id` to `members` in the six data tables | `CASCADE` | When a member is erased, all of their health data is erased with them, so no orphaned data is left behind. |

`CASCADE` can be dangerous for health data: a delete with a wrong condition silently removes the full history of every member it matches. Backups and checking the number of affected rows before committing protect against this.

---

## 6. Indexes

Primary keys and unique keys are indexes too.

| Index | Table and column | Reason |
|---|---|---|
| Primary key `(member_id, date)` | the four daily tables | finds one member's rows over a date range quickly |
| `uq_companies_name` | `companies(name)` | enforces unique names and speeds lookup by name |
| `uq_members_code` | `members(member_code)` | enforces unique codes and speeds lookup by code |
| `idx_members_company` | `members(company_id)` | fast "all members of one company"; also used by the foreign key |
| `idx_cleaning_log_run` | `cleaning_log(run_id)` | fast "show the lines of one cleaning run" |
| `idx_raw_load_batch` | `raw_daily_metrics(load_batch)` | find or remove everything that came from one data load (migration 003) |
| `idx_mood_date_member_score` | `mood_checkins(checkin_date, member_id, mood_score)` | the features query reads only the last 14 days; date first lets MySQL read just those rows, and the score inside the index means no trip back to the table (migration 006) |
| `idx_features_as_of` | `member_features(as_of)` | `build_member_features` starts with `DELETE ... WHERE as_of = date`; the primary key starts with `member_id`, so without this index MySQL scans every stored date (migration 006) |
| `idx_snap_as_of` | `member_snapshots(as_of)` | same reason for `build_member_snapshots`, and "all snapshots of one date" for export (migration 006) |

The primary keys `(member_id, date)` already serve the question "one member over a date range". The indexes above serve the opposite question, "every member in a window ending on a date". Section 12 shows what was measured.

---

## 7. Roles and least privilege

`sql/roles.sql` creates two roles and one user for each. Run it as root after `migrate.py` (the permission to run the procedures needs them to exist).

| Role | User | What it may do |
|---|---|---|
| `wb_etl` | `wb_etl_user` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` on the data tables (including `member_features`), and `EXECUTE` on `build_member_features` and `build_member_snapshots`. No `CREATE`, `ALTER`, `DROP` or `GRANT`. Used by the loader, the cleaning step and the snapshot build. |
| `wb_app` | `wb_app_user` | `SELECT` on `member_snapshots` and nothing else. **The insight service connects as `wb_app_user`.** |

`SET DEFAULT ROLE` is needed, otherwise MySQL 8 grants the role but the user logs in with no privileges.

**Why least privilege matters for health data.** `wb_etl` can read and write the data tables but cannot change the schema or grant rights. `wb_app` can only read `member_snapshots`. Each account gets only what its job needs. The data is health data (mood, heart rate, sleep), so a leaked password or a bug should expose as little as possible. If the insight service is hacked or has an SQL bug, it can only read snapshots. It cannot read raw member data, change or delete rows, or drop tables. The ETL account cannot drop tables either, so a bad loader script can't destroy the schema. Separate accounts also show who did what in the logs.

---

## 8. Data generation, loading and cleaning (1d)

**Generation.** `scripts/generate_data.py` creates 500 members (45,000 daily rows) and 5,000 members (450,000 daily rows) over 90 days. It writes one CSV per table. It writes CSV files that the bulk loader reads.

**Loading.** `scripts/load_data.py` uses `LOAD DATA LOCAL INFILE`, not row-by-row inserts. It runs in one transaction, so a failed load leaves nothing behind. `LOCAL` turns bad rows into warnings instead of errors, so the script checks the row count and warnings for every table.

| Size | Raw daily rows | Load time |
|---|---|---|
| 500 members | 45,000 | 1.50 s |
| 5,000 members | 450,000 | 14.20 s |

**Server setting changed.** `LOAD DATA LOCAL INFILE` is off by default in MySQL 8 (error 3948). I ran `SET PERSIST local_infile = 1;` as root. The client also has to allow it (`local_infile=True` in the Python connection).

**Cleaning in SQL.** `sql/clean_daily_metrics.sql` copies `raw_daily_metrics` into `daily_metrics` with `INSERT ... SELECT`. A `CASE` expression sets values outside the allowed range to NULL. The ranges match the CHECK constraints. The number removed per column is saved in `cleaning_log`.

| Column | Rule | 500 members: removed | 5,000 members: removed |
|---|---|---|---|
| steps | 0 to 60,000 | 10 of 41,788 | 86 of 415,904 |
| active_minutes | 0 to 600 | 4 of 41,788 | 42 of 415,904 |
| sleep_hours | 2.0 to 14.0 | 8 of 41,788 | 86 of 415,904 |
| resting_hr | 30 to 120 | 8 of 41,788 | 86 of 415,904 |

**Planted cases checked.** 14 members are planted to trigger escalation (3 or more low check-ins in their last 5) and 8 near-miss members have exactly 2. The generator now stops with an error if a pattern does not match its name. `tests/test_planted_cases.py` also asks MySQL, with a window function, to check every planted case in the loaded data: every escalation member has 3 or more low check-ins among the last 5, and every near-miss member has exactly 2. Ordinary members cannot meet the rule by accident.

---

## 9. Migrations (1b)

The schema is built by numbered files in `sql/migrations/`, applied in order by `scripts/migrate.py`.

| File | What it does |
|---|---|
| `001_schema.sql` | the first six tables: companies, members, raw_daily_metrics, daily_metrics, engagement, mood_checkins |
| `002_add_snapshots_and_log.sql` | adds two new tables: member_snapshots and cleaning_log |
| `003_add_load_batch.sql` | **changes an existing table without losing data**: adds `raw_daily_metrics.load_batch` and an index; rows that already existed get `'initial'` |
| `004_member_features.sql` | adds `member_features` and the procedure `build_member_features` |
| `005_add_snapshot_procedure.sql` | adds the procedure `build_member_snapshots` |
| `006_add_secondary_indexes.sql` | adds the secondary indexes (section 6) |

How `migrate.py` works:

- It creates the database and a table `schema_migrations` (one row per applied file) if they do not exist.
- It runs every file that is not in `schema_migrations`, in name order. After a file runs, it records the file name and commits, so the file and its record are saved together.
- Running it a second time is safe: files already recorded are skipped (`skip`).
- A limit of MySQL: `CREATE` and `ALTER` are committed immediately and cannot be rolled back. If a file fails halfway, the statements that already ran stay. So migration files are kept small and contain only the change. They never contain `CREATE DATABASE`, `USE` or `DROP DATABASE`.

Settings come from environment variables (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`), so no password is written in the code.

---

## 10. Features in SQL

Every member gets one row of features per "as of" date. The features are calculated in SQL only, with no pandas. The result is stored in `member_features` by the stored procedure `build_member_features(p_as_of DATE)`. Example: `CALL build_member_features('2026-09-28');`

### Why a stored procedure and not a view

- The features depend on a date that changes every time. A view cannot take a date as input, so it would need a fixed date or a session variable, and MySQL does not allow variables inside views.
- The procedure saves its result in a table. A saved row can be read quickly, rebuilt later and compared with an earlier run. A view would redo the whole calculation on every read.
- The procedure first deletes the rows of that date and then inserts them, so calling it twice gives the same result.
- It uses `SQL SECURITY INVOKER`, so it runs with the rights of the user who calls it. The ETL user needs no extra rights beyond `EXECUTE`.

### Rules

| Rule | Meaning |
|---|---|
| 7-day window | the as-of date and the 6 days before it |
| 30-day window | the as-of date and the 29 days before it |
| Source | the clean table `daily_metrics`, so out-of-range values are already NULL |
| Days without sync | all values are NULL, and `AVG` ignores NULL, so they are left out of every average |
| Mood window | check-ins in the 14 days up to and including the as-of date |

### The features

| Feature (column) | How it is calculated |
|---|---|
| `avg_steps_*`, `avg_active_*`, `avg_sleep_*`, `avg_hr_*` (7d and 30d) | `AVG(CASE WHEN the date is inside the 7-day window THEN value END)`. The `CASE` gives NULL outside the window, so one scan of the 30 days gives both averages |
| `steps_change_pct`, `active_change_pct`, `sleep_change_pct`, `hr_change_pct` | (7-day average - 30-day average) / 30-day average x 100, using the unrounded averages. `NULLIF` avoids dividing by zero |
| `app_opens_7d`, `app_opens_30d` | `SUM(app_opens)` inside each window, 0 if there are no rows |
| `days_since_last_app_open` | `DATEDIFF(as_of, newest date with at least 1 open)`. NULL if the member never opened the app |
| `app_streak` | days in a row up to the as-of date with at least 1 open. `ROW_NUMBER()` numbers the days from newest to oldest. The streak is the number of days before the first day with 0 opens |
| `active_streak` | the same idea with 30 or more active minutes. Days with no active-minutes value (unsynced) are removed first, so they are skipped. A synced day under 30 minutes ends the streak |
| `sync_rate_30d` | synced days / days in the window, from 0.000 to 1.000 |
| `mood_last5` | the newest 5 check-ins in the 14-day window, newest first, stored as JSON, for example `[5, 2, 2]` |
| `mood_low_count` | how many of those check-ins are 2 or below |

SQL techniques used: CTEs (`WITH`), window functions (`ROW_NUMBER() OVER`), conditional aggregation with `CASE`, and date functions (`DATE_SUB`, `DATEDIFF`). Members with no rows in a part still get a feature row, because the parts are joined with `LEFT JOIN`.

### Hand-calculated test

`tests/fixtures/` holds 2 members over 14 days. Member 1 has an unsynced day and a reading of 150,000 steps (impossible, so the cleaning step turns it into NULL). Member 2 has an unsynced day and a resting heart rate of 220. `tests/fixtures/EXPECTED.md` shows the expected features worked out by hand. `tests/test_features_fixture.py` builds a separate database (`wellbeing_test`) with `migrate.py`, loads the fixture, runs the cleaning step, calls the procedure and checks that every value equals the hand calculation. I also broke the SQL on purpose in four ways (wrong window length, wrong streak boundary, unsynced days not skipped, wrong mood window), and the test failed each time.

---

## 11. JSON snapshots

`build_member_snapshots(p_as_of DATE)` (migration 005) builds one JSON snapshot per member and stores it in `member_snapshots` (primary key `member_id, as_of`). It first calls `build_member_features` for the same date, so a snapshot is never built from old numbers. It deletes that date's snapshots before inserting, so running it twice gives the same result.

The snapshot is built in SQL only. `JSON_OBJECT('key', value, ...)` makes an object, and `JSON_ARRAY(a, b, ...)` makes a list. Here the four wearable metrics are one `JSON_ARRAY` of four `JSON_OBJECT`s.

```json
{
  "member_id": "M0042",
  "as_of": "2026-09-28",
  "wearable": [
    {"metric": "steps", "avg_7d": 9200.0, "avg_30d": 7625.0, "change_pct": 20.7},
    {"metric": "active_minutes", "avg_7d": 44.2, "avg_30d": 39.2, "change_pct": 12.6},
    {"metric": "sleep_hours", "avg_7d": 7.2, "avg_30d": 7.1, "change_pct": 0.7},
    {"metric": "resting_hr", "avg_7d": 61.3, "avg_30d": 61.5, "change_pct": -0.2}
  ],
  "sync_rate_30d": 0.929,
  "app": {"opens_7d": 8, "opens_30d": 17, "days_since_last_open": 0, "streak_days": 5, "active_streak_days": 11},
  "mood": {"last5": [5, 2, 2, 4, 1], "low_count": 3}
}
```

| Field | Meaning |
|---|---|
| `member_id` | the external member code, never the internal number, no name or email |
| `wearable[].avg_7d / avg_30d` | averages over 7 and 30 days, days without sync are ignored |
| `wearable[].change_pct` | % change of the 7-day average versus the 30-day average (the member's own baseline) |
| `sync_rate_30d` | share of the last 30 days with a wearable sync, 0 to 1 |
| `app` | app opens, days since the last open, and the two streaks in days |
| `mood.last5` | the last 5 check-ins in the last 14 days, newest first |
| `mood.low_count` | how many of those are 2 or below (3 or more means escalation, the service applies that rule) |

A value that does not exist (for example no synced day in the window) is stored as JSON `null`.

**Compact.** The longest snapshot on the 5,000-member set is 571 characters, about 140 tokens, far below the 1,500 token token budget I set. MySQL stores JSON keys in its own order (shorter keys first), so the order in the stored document can differ from the order written in the SQL. It does not change the meaning.

**Access.** `wb_etl` runs the procedure. `wb_app` can only `SELECT` from `member_snapshots` and cannot read `member_features` (tested: error 1142).

**Tests.** `tests/test_features_fixture.py` also builds the snapshots of the 2-member fixture and checks that each one equals the hand-calculated values from `EXPECTED.md`, that it contains the member code and not the internal number, and that building twice does not duplicate rows. Run all tests with `python -m pytest tests -v` (it needs `DB_USER` and `DB_PASSWORD` of an account that can create databases, and `ETL_PASSWORD` for `wb_etl_user`). Result: 11 passed.

---

## 12. Performance: EXPLAIN ANALYZE on the 5,000-member set

The features query is the SELECT inside `build_member_features`. `sql/explain_features.sql` runs it with `EXPLAIN ANALYZE` for 2026-09-28. `EXPLAIN ANALYZE` really runs the query and shows, for every step, how MySQL did it, the actual time in milliseconds (`actual time=first row..last row`) and the number of rows.

I ran it before the secondary indexes (migration 005) and after (migration 006), twice each time, and kept the second run. The same query, the same data and the same machine were used both times.

### Before (no extra indexes)

```
*************************** 1. row ***************************
EXPLAIN: -> Nested loop left join  (cost=5.24e+9 rows=0) (actual time=2028..2056 rows=5000 loops=1)
    -> Nested loop left join  (cost=4.23e+9 rows=0) (actual time=1960..1982 rows=5000 loops=1)
        -> Nested loop left join  (cost=4.13e+9 rows=0) (actual time=1333..1350 rows=5000 loops=1)
            -> Nested loop left join  (cost=4.12e+9 rows=41.2e+9) (actual time=682..695 rows=5000 loops=1)
                -> Nested loop left join  (cost=834421 rows=8.3e+6) (actual time=363..371 rows=5000 loops=1)
                    -> Filter: (m.join_date <= DATE'2026-09-28')  (cost=504 rows=1666) (actual time=0.305..2.81 rows=5000 loops=1)
                        -> Table scan on m  (cost=504 rows=5000) (actual time=0.302..2.11 rows=5000 loops=1)
                    -> Index lookup on ma using <auto_key0> (member_id=m.member_id)  (cost=50687..50690 rows=10) (actual time=0.0733..0.0734 rows=1 loops=5000)
                        -> Materialize CTE metric_agg  (cost=50687..50687 rows=4979) (actual time=362..362 rows=5000 loops=1)
                            -> Group aggregate: count(0), sum(daily_metrics.wearable_synced), avg((case when (daily_metrics.metric_date > ('2026-09-28' - interval 7 day)) then daily_metrics.steps end)), avg(daily_metrics.steps), avg((case when (daily_metrics.metric_date > ('2026-09-28' - interval 7 day)) then daily_metrics.active_minutes end)), avg(daily_metrics.active_minutes), avg((case when (daily_metrics.metric_date > ('2026-09-28' - interval 7 day)) then daily_metrics.sleep_hours end)), avg(daily_metrics.sleep_hours), avg((case when (daily_metrics.metric_date > ('2026-09-28' - interval 7 day)) then daily_metrics.resting_hr end)), avg(daily_metrics.resting_hr)  (cost=50189 rows=4979) (actual time=9.09..347 rows=5000 loops=1)
                                -> Filter: ((daily_metrics.metric_date > <cache>(('2026-09-28' - interval 30 day))) and (daily_metrics.metric_date <= DATE'2026-09-28'))  (cost=45198 rows=49915) (actual time=8.93..222 rows=150000 loops=1)
                                    -> Index scan on daily_metrics using PRIMARY  (cost=45198 rows=449329) (actual time=8.89..167 rows=450000 loops=1)
                -> Index lookup on ea using <auto_key0> (member_id=m.member_id)  (cost=60687..60694 rows=30) (actual time=0.0646..0.0647 rows=1 loops=5000)
                    -> Materialize CTE engagement_agg  (cost=60687..60687 rows=4966) (actual time=320..320 rows=5000 loops=1)
                        -> Group aggregate: sum((case when (engagement.activity_date > ('2026-09-28' - interval 7 day)) then engagement.app_opens else 0 end)), sum((case when (engagement.activity_date > ('2026-09-28' - interval 30 day)) then engagement.app_opens else 0 end)), max((case when (engagement.app_opens > 0) then engagement.activity_date end))  (cost=60190 rows=4966) (actual time=1.72..313 rows=5000 loops=1)
                            -> Filter: (engagement.activity_date <= DATE'2026-09-28')  (cost=45202 rows=149883) (actual time=1.67..146 rows=450000 loops=1)
                                -> Index scan on engagement using PRIMARY  (cost=45202 rows=449694) (actual time=1.67..105 rows=450000 loops=1)
            -> Index lookup on aps using <auto_key0> (member_id=m.member_id)  (cost=0.25..7.49 rows=30) (actual time=0.131..0.131 rows=1 loops=5000)
                -> Materialize CTE app_streak  (cost=0..0 rows=0) (actual time=650..650 rows=5000 loops=1)
                    -> Table scan on <temporary>  (actual time=646..646 rows=5000 loops=1)
                        -> Aggregate using temporary table  (actual time=646..646 rows=5000 loops=1)
                            -> Table scan on app_ranked  (cost=2.5..2.5 rows=0) (actual time=491..529 rows=450000 loops=1)
                                -> Materialize CTE app_ranked  (cost=0..0 rows=0) (actual time=491..491 rows=450000 loops=1)
                                    -> Window aggregate: row_number() OVER (PARTITION BY engagement.member_id ORDER BY engagement.activity_date desc )   (actual time=280..419 rows=450000 loops=1)
                                        -> Sort: engagement.member_id, engagement.activity_date DESC  (cost=45202 rows=449694) (actual time=280..311 rows=450000 loops=1)
                                            -> Filter: (engagement.activity_date <= DATE'2026-09-28')  (cost=45202 rows=449694) (actual time=1.68..140 rows=450000 loops=1)
                                                -> Table scan on engagement  (cost=45202 rows=449694) (actual time=1.67..102 rows=450000 loops=1)
        -> Index lookup on acs using <auto_key0> (member_id=m.member_id)  (cost=0.25..6.74 rows=27) (actual time=0.126..0.126 rows=1 loops=5000)
            -> Materialize CTE active_streak  (cost=0..0 rows=0) (actual time=627..627 rows=5000 loops=1)
                -> Table scan on <temporary>  (actual time=622..622 rows=5000 loops=1)
                    -> Aggregate using temporary table  (actual time=622..622 rows=5000 loops=1)
                        -> Table scan on active_ranked  (cost=2.5..2.5 rows=0) (actual time=481..515 rows=415862 loops=1)
                            -> Materialize CTE active_ranked  (cost=0..0 rows=0) (actual time=481..481 rows=415862 loops=1)
                                -> Window aggregate: row_number() OVER (PARTITION BY daily_metrics.member_id ORDER BY daily_metrics.metric_date desc )   (actual time=295..420 rows=415862 loops=1)
                                    -> Sort: daily_metrics.member_id, daily_metrics.metric_date DESC  (cost=45198 rows=449329) (actual time=295..321 rows=415862 loops=1)
                                        -> Filter: ((daily_metrics.metric_date <= DATE'2026-09-28') and (daily_metrics.active_minutes is not null))  (cost=45198 rows=449329) (actual time=1.54..163 rows=415862 loops=1)
                                            -> Table scan on daily_metrics  (cost=45198 rows=449329) (actual time=1.54..108 rows=450000 loops=1)
    -> Index lookup on mo using <auto_key0> (member_id=m.member_id)  (cost=2.85..5.1 rows=10) (actual time=0.0144..0.0145 rows=0.72 loops=5000)
        -> Materialize CTE mood_agg  (cost=2.6..2.6 rows=0) (actual time=68.6..68.6 rows=3599 loops=1)
            -> Group aggregate: group_concat(mood_ranked.mood_score order by mood_ranked.rn ASC separator ','), sum((mood_ranked.mood_score <= 2))  (cost=2.6..2.6 rows=0) (actual time=51.5..58.2 rows=3599 loops=1)
                -> Sort: mood_ranked.member_id  (cost=2.6..2.6 rows=0) (actual time=51.5..52.6 rows=12374 loops=1)
                    -> Filter: (mood_ranked.rn <= 5)  (cost=2.5..2.5 rows=0) (actual time=45.4..48 rows=12374 loops=1)
                        -> Table scan on mood_ranked  (cost=2.5..2.5 rows=0) (actual time=45.4..46.8 rows=14624 loops=1)
                            -> Materialize CTE mood_ranked  (cost=0..0 rows=0) (actual time=45.4..45.4 rows=14624 loops=1)
                                -> Window aggregate: row_number() OVER (PARTITION BY mood_checkins.member_id ORDER BY mood_checkins.checkin_date desc )   (actual time=34.9..41.5 rows=14624 loops=1)
                                    -> Sort: mood_checkins.member_id, mood_checkins.checkin_date DESC  (cost=10011 rows=99457) (actual time=34.9..36.5 rows=14624 loops=1)
                                        -> Filter: ((mood_checkins.checkin_date > <cache>(('2026-09-28' - interval 14 day))) and (mood_checkins.checkin_date <= DATE'2026-09-28'))  (cost=10011 rows=99457) (actual time=1.26..28.1 rows=14624 loops=1)
                                            -> Table scan on mood_checkins  (cost=10011 rows=99457) (actual time=1.25..20.3 rows=97741 loops=1)

1 row in set (2.09 sec)
```

### After (migration 006)

```
*************************** 1. row ***************************
EXPLAIN: -> Nested loop left join  (cost=5.24e+9 rows=0) (actual time=1975..2002 rows=5000 loops=1)
    -> Nested loop left join  (cost=4.23e+9 rows=0) (actual time=1937..1959 rows=5000 loops=1)
        -> Nested loop left join  (cost=4.13e+9 rows=0) (actual time=1310..1326 rows=5000 loops=1)
            -> Nested loop left join  (cost=4.12e+9 rows=41.2e+9) (actual time=656..668 rows=5000 loops=1)
                -> Nested loop left join  (cost=834421 rows=8.3e+6) (actual time=327..334 rows=5000 loops=1)
                    -> Filter: (m.join_date <= DATE'2026-09-28')  (cost=504 rows=1666) (actual time=0.0722..2.52 rows=5000 loops=1)
                        -> Table scan on m  (cost=504 rows=5000) (actual time=0.0712..1.9 rows=5000 loops=1)
                    -> Index lookup on ma using <auto_key0> (member_id=m.member_id)  (cost=50687..50690 rows=10) (actual time=0.0661..0.0662 rows=1 loops=5000)
                        -> Materialize CTE metric_agg  (cost=50687..50687 rows=4979) (actual time=327..327 rows=5000 loops=1)
                            -> Group aggregate: count(0), sum(daily_metrics.wearable_synced), avg((case when (daily_metrics.metric_date > ('2026-09-28' - interval 7 day)) then daily_metrics.steps end)), avg(daily_metrics.steps), avg((case when (daily_metrics.metric_date > ('2026-09-28' - interval 7 day)) then daily_metrics.active_minutes end)), avg(daily_metrics.active_minutes), avg((case when (daily_metrics.metric_date > ('2026-09-28' - interval 7 day)) then daily_metrics.sleep_hours end)), avg(daily_metrics.sleep_hours), avg((case when (daily_metrics.metric_date > ('2026-09-28' - interval 7 day)) then daily_metrics.resting_hr end)), avg(daily_metrics.resting_hr)  (cost=50189 rows=4979) (actual time=1.91..312 rows=5000 loops=1)
                                -> Filter: ((daily_metrics.metric_date > <cache>(('2026-09-28' - interval 30 day))) and (daily_metrics.metric_date <= DATE'2026-09-28'))  (cost=45198 rows=49915) (actual time=1.86..196 rows=150000 loops=1)
                                    -> Index scan on daily_metrics using PRIMARY  (cost=45198 rows=449329) (actual time=1.84..145 rows=450000 loops=1)
                -> Index lookup on ea using <auto_key0> (member_id=m.member_id)  (cost=60687..60694 rows=30) (actual time=0.0664..0.0666 rows=1 loops=5000)
                    -> Materialize CTE engagement_agg  (cost=60687..60687 rows=4966) (actual time=329..329 rows=5000 loops=1)
                        -> Group aggregate: sum((case when (engagement.activity_date > ('2026-09-28' - interval 7 day)) then engagement.app_opens else 0 end)), sum((case when (engagement.activity_date > ('2026-09-28' - interval 30 day)) then engagement.app_opens else 0 end)), max((case when (engagement.app_opens > 0) then engagement.activity_date end))  (cost=60190 rows=4966) (actual time=1.75..322 rows=5000 loops=1)
                            -> Filter: (engagement.activity_date <= DATE'2026-09-28')  (cost=45202 rows=149883) (actual time=1.68..149 rows=450000 loops=1)
                                -> Index scan on engagement using PRIMARY  (cost=45202 rows=449694) (actual time=1.68..106 rows=450000 loops=1)
            -> Index lookup on aps using <auto_key0> (member_id=m.member_id)  (cost=0.25..7.49 rows=30) (actual time=0.131..0.132 rows=1 loops=5000)
                -> Materialize CTE app_streak  (cost=0..0 rows=0) (actual time=654..654 rows=5000 loops=1)
                    -> Table scan on <temporary>  (actual time=649..650 rows=5000 loops=1)
                        -> Aggregate using temporary table  (actual time=649..649 rows=5000 loops=1)
                            -> Table scan on app_ranked  (cost=2.5..2.5 rows=0) (actual time=495..533 rows=450000 loops=1)
                                -> Materialize CTE app_ranked  (cost=0..0 rows=0) (actual time=495..495 rows=450000 loops=1)
                                    -> Window aggregate: row_number() OVER (PARTITION BY engagement.member_id ORDER BY engagement.activity_date desc )   (actual time=284..424 rows=450000 loops=1)
                                        -> Sort: engagement.member_id, engagement.activity_date DESC  (cost=45202 rows=449694) (actual time=284..316 rows=450000 loops=1)
                                            -> Filter: (engagement.activity_date <= DATE'2026-09-28')  (cost=45202 rows=449694) (actual time=1.68..144 rows=450000 loops=1)
                                                -> Table scan on engagement  (cost=45202 rows=449694) (actual time=1.68..104 rows=450000 loops=1)
        -> Index lookup on acs using <auto_key0> (member_id=m.member_id)  (cost=0.25..6.74 rows=27) (actual time=0.126..0.126 rows=1 loops=5000)
            -> Materialize CTE active_streak  (cost=0..0 rows=0) (actual time=628..628 rows=5000 loops=1)
                -> Table scan on <temporary>  (actual time=624..624 rows=5000 loops=1)
                    -> Aggregate using temporary table  (actual time=624..624 rows=5000 loops=1)
                        -> Table scan on active_ranked  (cost=2.5..2.5 rows=0) (actual time=481..518 rows=415862 loops=1)
                            -> Materialize CTE active_ranked  (cost=0..0 rows=0) (actual time=481..481 rows=415862 loops=1)
                                -> Window aggregate: row_number() OVER (PARTITION BY daily_metrics.member_id ORDER BY daily_metrics.metric_date desc )   (actual time=290..418 rows=415862 loops=1)
                                    -> Sort: daily_metrics.member_id, daily_metrics.metric_date DESC  (cost=45198 rows=449329) (actual time=290..317 rows=415862 loops=1)
                                        -> Filter: ((daily_metrics.metric_date <= DATE'2026-09-28') and (daily_metrics.active_minutes is not null))  (cost=45198 rows=449329) (actual time=1.52..159 rows=415862 loops=1)
                                            -> Table scan on daily_metrics  (cost=45198 rows=449329) (actual time=1.51..107 rows=450000 loops=1)
    -> Index lookup on mo using <auto_key0> (member_id=m.member_id)  (cost=2.85..5.1 rows=10) (actual time=0.0082..0.00833 rows=0.72 loops=5000)
        -> Materialize CTE mood_agg  (cost=2.6..2.6 rows=0) (actual time=37.7..37.7 rows=3599 loops=1)
            -> Group aggregate: group_concat(mood_ranked.mood_score order by mood_ranked.rn ASC separator ','), sum((mood_ranked.mood_score <= 2))  (cost=2.6..2.6 rows=0) (actual time=20.7..27.4 rows=3599 loops=1)
                -> Sort: mood_ranked.member_id  (cost=2.6..2.6 rows=0) (actual time=20.7..21.9 rows=12374 loops=1)
                    -> Filter: (mood_ranked.rn <= 5)  (cost=2.5..2.5 rows=0) (actual time=16.4..18.2 rows=12374 loops=1)
                        -> Table scan on mood_ranked  (cost=2.5..2.5 rows=0) (actual time=16.4..17.4 rows=14624 loops=1)
                            -> Materialize CTE mood_ranked  (cost=0..0 rows=0) (actual time=16.4..16.4 rows=14624 loops=1)
                                -> Window aggregate: row_number() OVER (PARTITION BY mood_checkins.member_id ORDER BY mood_checkins.checkin_date desc )   (actual time=11.3..14.9 rows=14624 loops=1)
                                    -> Sort: mood_checkins.member_id, mood_checkins.checkin_date DESC  (cost=5425 rows=26876) (actual time=11.3..12 rows=14624 loops=1)
                                        -> Filter: ((mood_checkins.checkin_date > <cache>(('2026-09-28' - interval 14 day))) and (mood_checkins.checkin_date <= DATE'2026-09-28'))  (cost=5425 rows=26876) (actual time=0.392..6.43 rows=14624 loops=1)
                                            -> Index range scan on mood_checkins using idx_mood_date_member_score over ('2026-09-14' < checkin_date <= '2026-09-28')  (cost=5425 rows=26876) (actual time=0.389..3.81 rows=14624 loops=1)

1 row in set (2.03 sec)
```

### What changed and why

| | Before | After |
|---|---|---|
| `mood_checkins` access | `Table scan`, 97,741 rows read | `Index range scan` using `idx_mood_date_member_score`, only the 14-day window |
| Estimated rows for the mood filter | 99,457 | 26,876 |
| `mood_agg` step | 68.6 ms | 37.7 ms |
| `app_streak` and `active_streak` steps | 650 ms and 627 ms | 654 ms and 628 ms (unchanged) |
| Whole query | 2028..2056 ms | 1975..2002 ms |

- **The mood step changed, and why.** Before, MySQL read all 97,741 rows of `mood_checkins` (`Table scan`) and then kept the 14,624 rows of the last 14 days. The primary key starts with `member_id`, so it could not answer "every member in the last 14 days". The new index `idx_mood_date_member_score (checkin_date, member_id, mood_score)` has `checkin_date` first, so MySQL jumps to the start of the window and reads only those rows (`Index range scan`). `mood_score` is inside the index, so MySQL never has to go back to the table. The step is nearly twice as fast.
- **The total barely moved** (about 2,050 ms before, about 2,000 ms after, which is within the normal difference between runs). The time is in the two streak steps (about 650 ms and 630 ms). They look at each member's whole history, so a date index cannot reduce the rows, and MySQL still sorts about 450,000 rows (`Sort: member_id, date DESC`) for the `ROW_NUMBER()` window. These lines are the same before and after. Going faster would need a change to the query (for example updating streaks each day instead of recalculating them from the whole history), not another index.
- **The `as_of` indexes** (`idx_features_as_of`, `idx_snap_as_of`) do not appear in the plan above, because the features query does not filter on `as_of`. They are for the `DELETE ... WHERE as_of = date` that each procedure starts with. The primary key starts with `member_id`, so without them MySQL scans every stored date, and the cost grows with every day that is stored. With only one date stored, MySQL correctly prefers a full scan, so the benefit comes as dates accumulate.

## 13. Looking a snapshot up by member code (migration 007)

The service finds a snapshot by the member code (`M0042`), but `member_snapshots` is keyed by the internal number `member_id`, and the service account `wb_app` may read nothing but this one table, so it cannot join to `members`. Migration 007 adds a STORED generated column `member_code` that MySQL fills automatically from the JSON (`snapshot->>'$.member_id'`) and an index `idx_snap_code_asof (member_code, as_of)`. The service query is `WHERE member_code = %s ORDER BY as_of DESC LIMIT 1`, so it uses that index and returns the newest snapshot. Because the column is generated, it cannot get out of step with the JSON.
