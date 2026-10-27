-- 004_member_features.sql : one row of features per member per as-of date, built by a stored procedure.
-- Window rules used everywhere below (assumptions): "7 days" = the as-of date and the 6 days before it,
-- "30 days" = the as-of date and the 29 days before it. Only the clean table daily_metrics is used for wearable data.
-- The streaks assume one engagement row per day (the data generator writes every day).

CREATE TABLE member_features (                                    -- the output table, one row per member per as-of date
  member_id                 INT UNSIGNED NOT NULL,                -- which member, same type as members.member_id
  as_of                     DATE NOT NULL,                        -- the date the features are calculated for
  avg_steps_7d              DECIMAL(8,1) NULL,                    -- average steps over 7 days, NULL if no synced day in the window
  avg_steps_30d             DECIMAL(8,1) NULL,                    -- same over 30 days
  avg_active_7d             DECIMAL(6,1) NULL,                    -- average active minutes, 7 days
  avg_active_30d            DECIMAL(6,1) NULL,                    -- average active minutes, 30 days
  avg_sleep_7d              DECIMAL(4,1) NULL,                    -- average sleep hours, 7 days (one decimal like the source column)
  avg_sleep_30d             DECIMAL(4,1) NULL,                    -- average sleep hours, 30 days
  avg_hr_7d                 DECIMAL(5,1) NULL,                    -- average resting heart rate, 7 days
  avg_hr_30d                DECIMAL(5,1) NULL,                    -- average resting heart rate, 30 days
  steps_change_pct          DECIMAL(7,1) NULL,                    -- % change of the 7 day average versus the 30 day average (can be negative), steps
  active_change_pct         DECIMAL(7,1) NULL,                    -- same for active minutes
  sleep_change_pct          DECIMAL(7,1) NULL,                    -- same for sleep hours
  hr_change_pct             DECIMAL(7,1) NULL,                    -- same for resting heart rate
  app_opens_7d              SMALLINT UNSIGNED NOT NULL,           -- total app opens in 7 days, 0 when none (a missing day means no opens)
  app_opens_30d             SMALLINT UNSIGNED NOT NULL,           -- total app opens in 30 days, max 30*500 = 15000 fits SMALLINT
  days_since_last_app_open  SMALLINT UNSIGNED NULL,               -- NULL means the member has never opened the app up to the as-of date
  app_streak                SMALLINT UNSIGNED NOT NULL,           -- consecutive days up to the as-of date with at least 1 app open
  active_streak             SMALLINT UNSIGNED NOT NULL,           -- consecutive measured days with 30+ active minutes, unsynced days skipped
  sync_rate_30d             DECIMAL(4,3) NULL,                    -- share of the last 30 days with a wearable sync, 0.000 to 1.000
  mood_last5                JSON NOT NULL,                        -- the last 5 check-ins within 14 days, newest first, e.g. [2,1,3]
  mood_low_count            TINYINT UNSIGNED NOT NULL,            -- how many of those check-ins are 2 or below
  PRIMARY KEY (member_id, as_of),                                 -- one row per member per date, also serves "features of one member"
  CONSTRAINT fk_feat_member FOREIGN KEY (member_id)               -- every feature row must belong to a real member
    REFERENCES members (member_id) ON DELETE CASCADE              -- if the member is deleted their features go too
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE PROCEDURE build_member_features(IN p_as_of DATE)           -- call it with the date you want, e.g. CALL build_member_features('2026-09-28')
  SQL SECURITY INVOKER                                            -- runs with the caller's own rights, not the creator's (least privilege)
BEGIN
  DELETE FROM member_features WHERE as_of = p_as_of;              -- calling it twice for one date gives the same result

  INSERT INTO member_features
    (member_id, as_of, avg_steps_7d, avg_steps_30d, avg_active_7d, avg_active_30d, avg_sleep_7d, avg_sleep_30d,
     avg_hr_7d, avg_hr_30d, steps_change_pct, active_change_pct, sleep_change_pct, hr_change_pct, app_opens_7d, app_opens_30d, days_since_last_app_open,
     app_streak, active_streak, sync_rate_30d, mood_last5, mood_low_count)
  WITH
  metric_agg AS (                                                 -- wearable averages and sync rate, one row per member
    SELECT member_id,
           AVG(CASE WHEN metric_date > DATE_SUB(p_as_of, INTERVAL 7 DAY) THEN steps END)          AS steps_7d,     -- CASE gives NULL outside 7 days and AVG skips NULL
           AVG(steps)                                                                             AS steps_30d,    -- every row here is inside 30 days, AVG skips NULL (unsynced / removed values)
           AVG(CASE WHEN metric_date > DATE_SUB(p_as_of, INTERVAL 7 DAY) THEN active_minutes END) AS active_7d,
           AVG(active_minutes)                                                                    AS active_30d,
           AVG(CASE WHEN metric_date > DATE_SUB(p_as_of, INTERVAL 7 DAY) THEN sleep_hours END)    AS sleep_7d,
           AVG(sleep_hours)                                                                       AS sleep_30d,
           AVG(CASE WHEN metric_date > DATE_SUB(p_as_of, INTERVAL 7 DAY) THEN resting_hr END)     AS hr_7d,
           AVG(resting_hr)                                                                        AS hr_30d,
           SUM(wearable_synced) / COUNT(*)                                                        AS sync_rate     -- synced days divided by days present in the window
    FROM daily_metrics
    WHERE metric_date > DATE_SUB(p_as_of, INTERVAL 30 DAY) AND metric_date <= p_as_of             -- the 30 day window
    GROUP BY member_id
  ),
  engagement_agg AS (                                             -- app opens and the last open, one row per member
    SELECT member_id,
           SUM(CASE WHEN activity_date > DATE_SUB(p_as_of, INTERVAL 7 DAY)  THEN app_opens ELSE 0 END) AS opens_7d,
           SUM(CASE WHEN activity_date > DATE_SUB(p_as_of, INTERVAL 30 DAY) THEN app_opens ELSE 0 END) AS opens_30d,
           MAX(CASE WHEN app_opens > 0 THEN activity_date END)                                         AS last_open   -- newest day with an open, looks at all history
    FROM engagement
    WHERE activity_date <= p_as_of                                -- never look past the as-of date
    GROUP BY member_id
  ),
  app_ranked AS (                                                 -- number each member's days, newest day = 1
    SELECT member_id, app_opens,
           ROW_NUMBER() OVER (PARTITION BY member_id ORDER BY activity_date DESC) AS rn
    FROM engagement
    WHERE activity_date <= p_as_of
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
    WHERE metric_date <= p_as_of AND active_minutes IS NOT NULL
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
    WHERE checkin_date > DATE_SUB(p_as_of, INTERVAL 14 DAY) AND checkin_date <= p_as_of
  ),
  mood_agg AS (                                                   -- keep the newest 5 and summarise them
    SELECT member_id,
           SUM(mood_score <= 2) AS low_count,                     -- a true comparison counts as 1
           CAST(CONCAT('[', GROUP_CONCAT(mood_score ORDER BY rn SEPARATOR ','), ']') AS JSON) AS last5   -- e.g. [2,1,3], newest first
    FROM mood_ranked
    WHERE rn <= 5
    GROUP BY member_id
  )
  SELECT m.member_id, p_as_of,
         ROUND(ma.steps_7d, 1),  ROUND(ma.steps_30d, 1),
         ROUND(ma.active_7d, 1), ROUND(ma.active_30d, 1),
         ROUND(ma.sleep_7d, 1),  ROUND(ma.sleep_30d, 1),
         ROUND(ma.hr_7d, 1),     ROUND(ma.hr_30d, 1),
         ROUND((ma.steps_7d  - ma.steps_30d)  / NULLIF(ma.steps_30d, 0)  * 100, 1),   -- NULLIF avoids dividing by zero
         ROUND((ma.active_7d - ma.active_30d) / NULLIF(ma.active_30d, 0) * 100, 1),
         ROUND((ma.sleep_7d  - ma.sleep_30d)  / NULLIF(ma.sleep_30d, 0)  * 100, 1),
         ROUND((ma.hr_7d     - ma.hr_30d)     / NULLIF(ma.hr_30d, 0)     * 100, 1),
         COALESCE(ea.opens_7d, 0), COALESCE(ea.opens_30d, 0),                      -- no engagement rows at all means 0 opens
         DATEDIFF(p_as_of, ea.last_open),                                          -- NULL if the member never opened the app
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
  WHERE m.join_date <= p_as_of;                                                    -- members who had not joined yet get no row
END;
