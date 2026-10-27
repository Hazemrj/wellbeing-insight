-- 005_add_snapshot_procedure.sql : builds one compact JSON snapshot per member and stores it in member_snapshots.
-- The table already exists (migration 002). This migration only adds the procedure that fills it.
--
-- Snapshot shape (one JSON document per member per date). Only the external code M0042 is inside, no name or email.
--   {
--     "member_id": "M0042",                                  the member_code, never the internal number
--     "as_of": "2026-09-28",
--     "wearable": [ {"metric": "steps", "avg_7d": 9200.0, "avg_30d": 7625.0, "change_pct": 20.7},
--                   {"metric": "active_minutes", ...}, {"metric": "sleep_hours", ...}, {"metric": "resting_hr", ...} ],
--     "sync_rate_30d": 0.929,
--     "app":  {"opens_7d": 8, "opens_30d": 17, "days_since_last_open": 0, "streak_days": 5, "active_streak_days": 11},
--     "mood": {"last5": [5, 2, 2, 4, 1], "low_count": 3}     last 5 check-ins in 14 days, newest first, how many are 2 or below
--   }
-- A value that does not exist (for example no synced day in the window) is stored as JSON null.

CREATE PROCEDURE build_member_snapshots(IN p_as_of DATE)         -- call it with the date you want, e.g. CALL build_member_snapshots('2026-09-28')
  SQL SECURITY INVOKER                                            -- runs with the caller's own rights (least privilege)
BEGIN
  CALL build_member_features(p_as_of);                            -- first rebuild the features for that date, so a snapshot is never built from old numbers
  DELETE FROM member_snapshots WHERE as_of = p_as_of;             -- calling it twice for one date gives the same result

  INSERT INTO member_snapshots (member_id, as_of, snapshot)       -- created_at fills itself with the current time
  SELECT f.member_id, f.as_of,
         JSON_OBJECT(                                             -- JSON_OBJECT('key', value, ...) builds one JSON object
           'member_id', m.member_code,                            -- the external code, so the internal integer id never leaves the database
           'as_of', f.as_of,
           'wearable', JSON_ARRAY(                                -- JSON_ARRAY(a, b, ...) builds a list; here one object per wearable metric
             JSON_OBJECT('metric', 'steps',          'avg_7d', f.avg_steps_7d,  'avg_30d', f.avg_steps_30d,  'change_pct', f.steps_change_pct),
             JSON_OBJECT('metric', 'active_minutes', 'avg_7d', f.avg_active_7d, 'avg_30d', f.avg_active_30d, 'change_pct', f.active_change_pct),
             JSON_OBJECT('metric', 'sleep_hours',    'avg_7d', f.avg_sleep_7d,  'avg_30d', f.avg_sleep_30d,  'change_pct', f.sleep_change_pct),
             JSON_OBJECT('metric', 'resting_hr',     'avg_7d', f.avg_hr_7d,     'avg_30d', f.avg_hr_30d,     'change_pct', f.hr_change_pct)
           ),
           'sync_rate_30d', f.sync_rate_30d,
           'app', JSON_OBJECT('opens_7d', f.app_opens_7d, 'opens_30d', f.app_opens_30d,
                              'days_since_last_open', f.days_since_last_app_open,
                              'streak_days', f.app_streak, 'active_streak_days', f.active_streak),
           'mood', JSON_OBJECT('last5', f.mood_last5, 'low_count', f.mood_low_count)   -- last5 is already a JSON list from the feature step
         )
  FROM member_features f
  JOIN members m ON m.member_id = f.member_id                     -- we need member_code from the members table
  WHERE f.as_of = p_as_of;                                        -- only the date we just built
END;
