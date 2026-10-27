# wellbeing-insight

A MySQL 8 database for wearable, app-use and mood data, a pure-SQL feature pipeline that builds one JSON snapshot per member, and a small API that turns a snapshot into a short, safe coaching message using a local language model. All data is synthetic.

The design idea: **the model never reads the database.** It reads a small prepared snapshot, its answer is checked in code before anyone sees it, and the safety decision (escalating a member whose mood is low) is made in code before the model is involved.

```
CSV files -> raw tables -> SQL cleaning -> daily_metrics -> build_member_features -> build_member_snapshots
                                                                                          |
                          POST /insight  <-  checks  <-  local model  <-  member_snapshots (read-only account)
```

## What is in it

- **Schema and migrations:** six tables with keys, foreign keys and CHECK constraints, plus numbered migrations (`sql/migrations/001` to `007`) applied by `scripts/migrate.py`, which is safe to run twice.
- **Least privilege:** two MySQL roles. `wb_etl` loads and cleans data; `wb_app` can only `SELECT` from `member_snapshots`.
- **Data pipeline:** a synthetic data generator (500 and 5,000 members, 90 days, with planted edge cases and an answer key), bulk loading with `LOAD DATA LOCAL INFILE`, and a cleaning step in SQL that logs what it removed.
- **Features in SQL:** a stored procedure with CTEs and window functions (7/30 day averages, change %, app streaks, active streak, sync rate, last 5 mood scores). A second procedure builds JSON snapshots with `JSON_OBJECT` and `JSON_ARRAY`.
- **Hand-calculated test:** a 2-member, 14-day fixture whose expected values were worked out by hand (`tests/fixtures/EXPECTED.md`); a pytest test checks that the SQL returns exactly those values.
- **Insight service (FastAPI):** reads a snapshot with a parameterized query, escalates in code, asks a local model (Ollama, `qwen2.5:3b`), validates the answer, retries once, and falls back to a safe fixed message.
- **Guardrails:** JSON shape, numbers must exist in the snapshot, no medical wording, direction of change must be right, evidence values must match their own field, no persona or model-internal wording, Arabic-Indic digits normalised. Each fix has its own regression test file. Known gaps are in `docs/GUARDRAILS.md`.
- **Evaluation:** 30 members labelled by hand, compared with the checker; escalation scored against the generator's answer key; a risk model with the threshold chosen on validation data (nested cross-validation).

## Results (500 members, local `qwen2.5:3b` on a CPU)

| Metric | Result |
|---|---|
| Valid JSON, final answers | 30/30 |
| Escalation vs answer key, all 500 members | 100% (14 of 14 found, 0 false alarms) |
| Checker agrees with hand labels | 29/30 (the one disagreement is listed in `reports/eval/EVAL_REPORT.md`) |
| Model answers accepted on the first try | 16/25 (8 needed the retry, 1 fell back) |
| Latency, answers that called the model | average 22.6 s, 95th percentile 35.0 s (CPU only) |
| Risk model (no app opens in the next 14 days) | precision 0.92, recall 0.83, against 0.87 / 0.85 for the rule "no app open in 7 days"; only 65 positive cases, so folds vary a lot |

## Example output

These are real responses from the service running with the scripted stand-in model (`LLM_BACKEND=mock`), so you can see the shape without installing a model. With Ollama the `insight` text is written by the model; everything else, including the checks, is the same.

**An ordinary member** (`POST /insight` with `{"member_id": "M0042"}`):
```json
{
  "member_id": "M0042",
  "insight": "Your active minutes rose compared with your usual level this week. Small steady habits add up.",
  "evidence": ["active_minutes_7d: 17.7 vs baseline 16.4 (+7.8%)"],
  "actions": [
    "Take a 10 minute walk after one meal on three days.",
    "Pick a regular bedtime and keep it for the next few nights."
  ],
  "tone": "encouraging",
  "safety_flag": false,
  "meta": {"source": "llm", "attempts": 1, "backend": "mock", "problems": [], "latency_ms": 52}
}
```

**A member whose last 5 mood check-ins are `[2, 2, 3, 1, 2]`.** Four of the five are 2 or lower, so the code escalates before any model is called and returns a fixed supportive message:
```json
{
  "member_id": "M0030",
  "insight": "Your recent mood check-ins have been low, and that matters more than any step or sleep goal this week. You don't have to work through this alone.",
  "evidence": ["recent_mood_checkins: 2, 2, 3, 1, 2"],
  "actions": [
    "Please consider talking with a qualified professional, such as your doctor or a counsellor, this week.",
    "Reach out to someone you trust, and use your company's confidential support service if you have one."
  ],
  "tone": "supportive",
  "safety_flag": true,
  "meta": {"source": "escalation_template", "attempts": 0, "backend": "mock", "problems": [], "latency_ms": 50}
}
```

**Errors:** an unknown member gives `404` (`{"detail": "no snapshot for this member"}`), an id that is not `M` plus four digits gives `422`, and an unreachable database gives `503`.

## Requirements

- Python 3.11 or newer
- MySQL 8.0 or newer on `127.0.0.1:3306` with an admin account
- Optional: [Ollama](https://ollama.com) with `ollama pull qwen2.5:3b`. Without it everything works except live model answers; the tests use a scripted stand-in model.

Allow bulk loading once, as the MySQL admin:
```
mysql -u root -p -e "SET GLOBAL local_infile = 1;"
```

## Set up

The commands are for Windows `cmd`. On Linux or macOS use `export NAME=value` instead of `set NAME=value`, and `source .venv/bin/activate`.

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Passwords come from environment variables (set them in every new terminal window):
```
set DB_USER=root
set DB_PASSWORD=YOUR_ADMIN_PASSWORD
set ETL_PASSWORD=change_me_etl
set APP_DB_PASSWORD=change_me_app
```
`DB_USER` and `DB_PASSWORD` are an admin account (create the tables, run one test). `ETL_PASSWORD` and `APP_DB_PASSWORD` belong to the two limited users created below; change them in `sql/roles.sql` first if you want other passwords.

```
python scripts\migrate.py                                   # creates the database and tables
mysql -u root -p < sql\roles.sql                            # creates the two roles and users
python scripts\generate_data.py --members 500 --out data\n500 --seed 42
python scripts\load_data.py --data-dir data\n500 --label n500
python scripts\clean_data.py
mysql -u wb_etl_user -p wellbeing -e "CALL build_member_snapshots('2026-09-28')"
```

## Tests

```
python -m pytest tests -q
```
All tests pass (192). They need the passwords above and the data loaded; `tests/test_features_fixture.py` builds and drops its own database `wellbeing_test`.

## Run the service

With the real model (Ollama running):
```
python -m uvicorn service.app:app --port 8000
```
Without a model (a scripted stand-in; answers are labelled `"backend": "mock"`):
```
set LLM_BACKEND=mock
python -m uvicorn service.app:app --port 8000
```
Then:
```
curl -X POST http://127.0.0.1:8000/insight -H "Content-Type: application/json" -d "{\"member_id\": \"M0042\"}"
```
Status codes: `200` answer, `404` no snapshot for that member, `422` invalid member id, `503` database unavailable. Set `KEEP_REJECTED=1` to keep the text of rejected first attempts in `meta.rejected`. Set `OLLAMA_NUM_GPU=0` to force the CPU.

## Evaluation

```
python scripts\eval_run.py --truth data\n500\ground_truth.csv       (service must be running)
```
Read `reports\eval\review_sheet.md`, fill `reports\eval\labels.csv` (yes/no per member), then:
```
python scripts\eval_report.py --truth data\n500\ground_truth.csv
python scripts\risk_model.py
```

## Layout

```
sql/migrations/   schema changes, applied in order by scripts/migrate.py
sql/roles.sql     the two roles and users
sql/*.sql         cleaning query, EXPLAIN ANALYZE script
scripts/          migrate, generate, load, clean, risk model, evaluation
service/          database access, prompt, model clients, guardrails, flow, API
tests/            pytest tests and the hand-calculated fixture
docs/             DATABASE.md (design, indexes, query plans), GUARDRAILS.md (checks and known gaps)
reports/          evaluation report and risk model result
```

## Limits

The checker is built from word lists and rules, so it misses synonyms, typos and other languages, and its direction check can reject correct sentences such as "you're staying active". There is no login on the API. On a CPU the model needs 13 to 38 seconds per answer. The data is synthetic, so the numbers say how the system behaves, not how real members behave.
