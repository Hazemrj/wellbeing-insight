-- 006_add_secondary_indexes.sql : the secondary indexes the feature queries need. No data is changed or lost.
-- Kept as its own migration so EXPLAIN ANALYZE can be run at version 005 (before) and again at 006 (after).
-- Only indexes that made a measurable difference are here (see docs/DATABASE.md for what was measured and what was not kept).

ALTER TABLE mood_checkins                                                          -- one row per check-in, primary key starts with member_id
  ADD INDEX idx_mood_date_member_score (checkin_date, member_id, mood_score);      -- the features query reads only the last 14 days: date first lets MySQL read just those rows, and mood_score inside the index means no trip back to the table

ALTER TABLE member_features                                                        -- primary key (member_id, as_of) cannot be used when we only know the date
  ADD INDEX idx_features_as_of (as_of);                                            -- build_member_features starts with DELETE ... WHERE as_of = date: with the index it finds that date's rows directly instead of scanning every stored date

ALTER TABLE member_snapshots                                                       -- same situation as member_features
  ADD INDEX idx_snap_as_of (as_of);                                                -- build_member_snapshots also starts with DELETE ... WHERE as_of = date, and "all snapshots of one date" is the natural export query
