-- clean_daily_metrics.sql : rebuild daily_metrics from raw_daily_metrics, set out-of-range values to NULL, log what was removed.
-- The ranges here match the CHECK constraints in 001_schema.sql. Run it with scripts/clean_data.py.

SET @run_id = UUID();                                             -- one unique id shared by every log line of this run
SET @run_at = NOW();                                              -- when the run started (UTC)

DELETE FROM daily_metrics;                                        -- start from empty so running the cleaning twice gives the same result

INSERT INTO daily_metrics                                         -- copy raw rows into the clean table ...
  (member_id, metric_date, steps, active_minutes, sleep_hours, resting_hr, wearable_synced)
SELECT
  r.member_id,                                                    -- same member
  r.metric_date,                                                  -- same day
  CASE WHEN r.wearable_synced = 1 AND r.steps          BETWEEN 0   AND 60000 THEN r.steps          END,   -- keep only plausible steps, else NULL (CASE without ELSE gives NULL)
  CASE WHEN r.wearable_synced = 1 AND r.active_minutes BETWEEN 0   AND 600   THEN r.active_minutes END,   -- keep only plausible active minutes
  CASE WHEN r.wearable_synced = 1 AND r.sleep_hours    BETWEEN 2.0 AND 14.0  THEN ROUND(r.sleep_hours, 1) END, -- keep only plausible sleep, one decimal
  CASE WHEN r.wearable_synced = 1 AND r.resting_hr     BETWEEN 30  AND 120   THEN r.resting_hr     END,   -- keep only plausible resting heart rate
  r.wearable_synced                                               -- the sync flag is copied unchanged
FROM raw_daily_metrics AS r;                                      -- the audit copy stays untouched

-- Log how many values were removed per column: compare what arrived (raw, non-NULL) with what survived (clean).
INSERT INTO cleaning_log (run_id, run_at, column_name, rule_text, values_received, values_removed)
SELECT @run_id, @run_at, 'steps', 'kept only 0 to 60000', COUNT(r.steps), COALESCE(SUM(d.steps IS NULL), 0)
FROM raw_daily_metrics r JOIN daily_metrics d ON d.member_id = r.member_id AND d.metric_date = r.metric_date
WHERE r.steps IS NOT NULL                                         -- only values that actually arrived can be "removed"
UNION ALL
SELECT @run_id, @run_at, 'active_minutes', 'kept only 0 to 600', COUNT(r.active_minutes), COALESCE(SUM(d.active_minutes IS NULL), 0)
FROM raw_daily_metrics r JOIN daily_metrics d ON d.member_id = r.member_id AND d.metric_date = r.metric_date
WHERE r.active_minutes IS NOT NULL
UNION ALL
SELECT @run_id, @run_at, 'sleep_hours', 'kept only 2.0 to 14.0', COUNT(r.sleep_hours), COALESCE(SUM(d.sleep_hours IS NULL), 0)
FROM raw_daily_metrics r JOIN daily_metrics d ON d.member_id = r.member_id AND d.metric_date = r.metric_date
WHERE r.sleep_hours IS NOT NULL
UNION ALL
SELECT @run_id, @run_at, 'resting_hr', 'kept only 30 to 120', COUNT(r.resting_hr), COALESCE(SUM(d.resting_hr IS NULL), 0)
FROM raw_daily_metrics r JOIN daily_metrics d ON d.member_id = r.member_id AND d.metric_date = r.metric_date
WHERE r.resting_hr IS NOT NULL;
