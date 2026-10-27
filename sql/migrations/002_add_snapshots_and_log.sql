-- 002_add_snapshots_and_log.sql : adds two NEW tables.

CREATE TABLE member_snapshots (                                       -- start defining the snapshot table
  member_id   INT UNSIGNED NOT NULL,                                  -- which member the snapshot describes
  as_of       DATE NOT NULL,                                          -- the date the snapshot was calculated for
  snapshot    JSON NOT NULL,                                          -- the compact summary the model reads, MySQL validates it is real JSON
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,            -- when the row was built, DATETIME has no 2038 limit, we store UTC
  PRIMARY KEY (member_id, as_of),                                     -- one snapshot per member per date
  CONSTRAINT fk_snap_member FOREIGN KEY (member_id)                   -- every snapshot must belong to a real member
    REFERENCES members (member_id) ON DELETE CASCADE                  -- CASCADE: a snapshot is derived health data, so it goes with the member
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;   -- same engine, character set and collation as every table


CREATE TABLE cleaning_log (                                           -- start defining the cleaning log table
  log_id          INT UNSIGNED NOT NULL AUTO_INCREMENT,               -- surrogate key, the server numbers the rows
  run_id          CHAR(36) NOT NULL,                                  -- a UUID that groups the 4 lines of one run (a timestamp could collide within one second)
  run_at          DATETIME NOT NULL,                                  -- when the cleaning run started (UTC)
  column_name     VARCHAR(32) NOT NULL,                               -- which column was cleaned, for example steps
  rule_text       VARCHAR(120) NOT NULL,                              -- the rule in words, so the log explains itself
  values_received INT UNSIGNED NOT NULL,                              -- how many non-NULL raw values were looked at
  values_removed  INT UNSIGNED NOT NULL,                              -- how many of them were set to NULL because they were out of range
  PRIMARY KEY (log_id),                                               -- identifies one log line
  KEY idx_cleaning_log_run (run_id)                                   -- fast "show me the lines of one run"
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;   -- same engine, character set and collation as every table
