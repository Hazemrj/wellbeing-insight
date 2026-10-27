-- 007_snapshot_member_code.sql : lets the insight service find a snapshot by member code (M0042) quickly.
-- Why: wb_app may only read member_snapshots, so it cannot JOIN the members table to turn M0042 into the internal number.
-- The code is already inside the JSON, so MySQL copies it out into a real column that can have an index. No data is lost.

ALTER TABLE member_snapshots                                                   -- change the existing table, do not drop or recreate it
  ADD COLUMN member_code VARCHAR(10)                                           -- the external code, e.g. M0042 (10 characters is plenty)
      GENERATED ALWAYS AS (JSON_UNQUOTE(JSON_EXTRACT(snapshot, '$.member_id'))) STORED,  -- MySQL fills it from the JSON itself, so it can never disagree with the snapshot
  ADD INDEX idx_snap_code_asof (member_code, as_of);                           -- "latest snapshot of M0042" becomes an index lookup instead of reading every row
