-- explain_features.sql : EXPLAIN ANALYZE of the features query (the SELECT inside build_member_features, migration 004).
-- Run it from the MySQL client:   source sql/explain_features.sql
-- It runs the query for real and shows how MySQL executed it and how long each step took.
-- Run it once BEFORE the secondary indexes (migration 006) and once AFTER, then paste both plans into docs/DATABASE.md.
-- Run it twice each time and keep the second result (the first one also has to load data from disk into memory).

USE wellbeing;                                            -- the as-of date is written directly in the query as '2026-09-28'
EXPLAIN ANALYZE
WITH
  metric_agg AS (                                                 -- wearable averages and sync rate, one row per member
    SELECT member_id,
           AVG(CASE WHEN metric_date > DATE_SUB('2026-09-28', INTERVAL 7 DAY) THEN steps END)          AS steps_7d,     -- CASE gives NULL outside 7 days and AVG skips NULL
           AVG(steps)                                                                             AS steps_30d,    -- every row here is inside 30 days, AVG skips NULL (unsynced / removed values)
           AVG(CASE WHEN metric_date > DATE_SUB('2026-09-28', INTERVAL 7 DAY) THEN active_minutes END) AS active_7d,
           AVG(active_minutes)                                                                    AS active_30d,
           AVG(CASE WHEN metric_date > DATE_SUB('2026-09-28', INTERVAL 7 DAY) THEN sleep_hours END)    AS sleep_7d,
           AVG(sleep_hours)                                                                       AS sleep_30d,
           AVG(CASE WHEN metric_date > DATE_SUB('2026-09-28', INTERVAL 7 DAY) THEN resting_hr END)     AS hr_7d,
           AVG(resting_hr)                                                                        AS hr_30d,
           SUM(wearable_synced) / COUNT(*)                                                        AS sync_rate     -- synced days divided by days present in the window
    FROM daily_metrics
    WHERE metric_date > DATE_SUB('2026-09-28', INTERVAL 30 DAY) AND metric_date <= '2026-09-28'             -- the 30 day window
    GROUP BY member_id
  ),
  engagement_agg AS (                                             -- app opens and the last open, one row per member
    SELECT member_id,
           SUM(CASE WHEN activity_date > DATE_SUB('2026-09-28', INTERVAL 7 DAY)  THEN app_opens ELSE 0 END) AS opens_7d,
           SUM(CASE WHEN activity_date > DATE_SUB('2026-09-28', INTERVAL 30 DAY) THEN app_opens ELSE 0 END) AS opens_30d,
           MAX(CASE WHEN app_opens > 0 THEN activity_date END)                                         AS last_open   -- newest day with an open, looks at all history
    FROM engagement
    WHERE activity_date <= '2026-09-28'                                -- never look past the as-of date
    GROUP BY member_id
  ),
  app_ranked AS (                                                 -- number each member's days, newest day = 1
    SELECT member_id, app_opens,
           ROW_NUMBER() OVER (PARTITION BY member_id ORDER BY activity_date DESC) AS rn
    FROM engagement
    WHERE activity_date <= '2026-09-28'
  ),
  app_streak AS (                                                 -- streak = number of days before the first day with 0 opens
    SELECT member_id,
           COALESCE(MIN(CASE WHEN app_opens = 0 THEN rn END) - 1, COUNT(*)) AS streak   -- no zero day at all: every day counts
    FROM app_ranked
    GROUP BY member_id
  ),
  active_ranked AS (                                              -- only days with a real active_minutes value, so unsynced days are skipped
    SELECT member_id, active_minutes,
           ROW_NUMBER() OVER (PARTITION BY member_id ORDER BY metric_date DESC) AS rn
    FROM daily_metrics
    WHERE metric_date <= '2026-09-28' AND active_minutes IS NOT NULL
  ),
  active_streak AS (                                              -- streak = number of days before the first day under 30 minutes
    SELECT member_id,
           COALESCE(MIN(CASE WHEN active_minutes < 30 THEN rn END) - 1, COUNT(*)) AS streak
    FROM active_ranked
    GROUP BY member_id
  ),
  mood_ranked AS (                                                -- check-ins of the last 14 days, newest = 1
    SELECT member_id, mood_score,
           ROW_NUMBER() OVER (PARTITION BY member_id ORDER BY checkin_date DESC) AS rn
    FROM mood_checkins
    WHERE checkin_date > DATE_SUB('2026-09-28', INTERVAL 14 DAY) AND checkin_date <= '2026-09-28'
  ),
  mood_agg AS (                                                   -- keep the newest 5 and summarise them
    SELECT member_id,
           SUM(mood_score <= 2) AS low_count,                     -- a true comparison counts as 1
           CAST(CONCAT('[', GROUP_CONCAT(mood_score ORDER BY rn SEPARATOR ','), ']') AS JSON) AS last5   -- e.g. [2,1,3], newest first
    FROM mood_ranked
    WHERE rn <= 5
    GROUP BY member_id
  )
  SELECT m.member_id, '2026-09-28',
         ROUND(ma.steps_7d, 1),  ROUND(ma.steps_30d, 1),
         ROUND(ma.active_7d, 1), ROUND(ma.active_30d, 1),
         ROUND(ma.sleep_7d, 1),  ROUND(ma.sleep_30d, 1),
         ROUND(ma.hr_7d, 1),     ROUND(ma.hr_30d, 1),
         ROUND((ma.steps_7d  - ma.steps_30d)  / NULLIF(ma.steps_30d, 0)  * 100, 1),   -- NULLIF avoids dividing by zero
         ROUND((ma.active_7d - ma.active_30d) / NULLIF(ma.active_30d, 0) * 100, 1),
         ROUND((ma.sleep_7d  - ma.sleep_30d)  / NULLIF(ma.sleep_30d, 0)  * 100, 1),
         ROUND((ma.hr_7d     - ma.hr_30d)     / NULLIF(ma.hr_30d, 0)     * 100, 1),
         COALESCE(ea.opens_7d, 0), COALESCE(ea.opens_30d, 0),                      -- no engagement rows at all means 0 opens
         DATEDIFF('2026-09-28', ea.last_open),                                          -- NULL if the member never opened the app
         COALESCE(aps.streak, 0), COALESCE(acs.streak, 0),
         ROUND(ma.sync_rate, 3),
         COALESCE(mo.last5, JSON_ARRAY()),                                         -- no check-ins gives an empty list []
         COALESCE(mo.low_count, 0)
  FROM members m
  LEFT JOIN metric_agg     ma  ON ma.member_id  = m.member_id                      -- LEFT JOIN keeps members who have no rows in a part
  LEFT JOIN engagement_agg ea  ON ea.member_id  = m.member_id
  LEFT JOIN app_streak     aps ON aps.member_id = m.member_id
  LEFT JOIN active_streak  acs ON acs.member_id = m.member_id
  LEFT JOIN mood_agg       mo  ON mo.member_id  = m.member_id
  WHERE m.join_date <= '2026-09-28'                                                    -- members who had not joined yet get no row
\G
