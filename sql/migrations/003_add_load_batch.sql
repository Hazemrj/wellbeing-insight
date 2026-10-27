-- 003_add_load_batch.sql : changes an EXISTING table without losing any row.
-- Why did I decide to make this change?: later, we will load several datasets, so each raw row should say which load it came from.

ALTER TABLE raw_daily_metrics                                                          -- change the existing raw table 
  ADD COLUMN load_batch VARCHAR(32) NOT NULL DEFAULT 'initial' AFTER wearable_synced,  -- label of the load, rows that already exist get 'initial'
  ADD INDEX idx_raw_load_batch (load_batch);                                           -- find or remove everything from one load quickly
