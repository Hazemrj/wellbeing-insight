-- two roles and one user for each. Run ONCE as an admin (root):  mysql -u root -p < sql/roles.sql
-- Run it AFTER python scripts/migrate.py (the EXECUTE grant needs the procedure to exist), and again after any new procedure.
-- Change both passwords before using this anywhere except your own laptop.

-- 1. Roles: named bundles of privileges.
CREATE ROLE IF NOT EXISTS 'wb_etl';   -- the data loading and cleaning job
CREATE ROLE IF NOT EXISTS 'wb_app';   -- the insight service

-- 2. Privileges for each role.
-- wb_etl: read and write the raw and clean tables. No CREATE/ALTER/DROP, no GRANT.
GRANT SELECT, INSERT, UPDATE, DELETE ON wellbeing.companies         TO 'wb_etl';
GRANT SELECT, INSERT, UPDATE, DELETE ON wellbeing.members           TO 'wb_etl';
GRANT SELECT, INSERT, UPDATE, DELETE ON wellbeing.raw_daily_metrics TO 'wb_etl';
GRANT SELECT, INSERT, UPDATE, DELETE ON wellbeing.daily_metrics     TO 'wb_etl';
GRANT SELECT, INSERT, UPDATE, DELETE ON wellbeing.engagement        TO 'wb_etl';
GRANT SELECT, INSERT, UPDATE, DELETE ON wellbeing.mood_checkins     TO 'wb_etl';
GRANT SELECT, INSERT, UPDATE, DELETE ON wellbeing.member_snapshots  TO 'wb_etl';
GRANT SELECT, INSERT, UPDATE, DELETE ON wellbeing.cleaning_log      TO 'wb_etl';
GRANT SELECT, INSERT, UPDATE, DELETE ON wellbeing.member_features   TO 'wb_etl';   -- the features table
GRANT EXECUTE ON PROCEDURE wellbeing.build_member_features           TO 'wb_etl';   -- may call the procedure (needs migration 004 first)
GRANT EXECUTE ON PROCEDURE wellbeing.build_member_snapshots          TO 'wb_etl';   -- may build snapshots (needs migration 005 first)

-- wb_app: can only READ one table.
GRANT SELECT ON wellbeing.member_snapshots TO 'wb_app';

-- 3. One user per role.
CREATE USER IF NOT EXISTS 'wb_etl_user'@'localhost' IDENTIFIED BY 'change_me_etl';
CREATE USER IF NOT EXISTS 'wb_app_user'@'localhost' IDENTIFIED BY 'change_me_app';
GRANT 'wb_etl' TO 'wb_etl_user'@'localhost';
GRANT 'wb_app' TO 'wb_app_user'@'localhost';

-- 4. Make the role active at login. Without this, the user logs in with NO privileges.
SET DEFAULT ROLE 'wb_etl' TO 'wb_etl_user'@'localhost';
SET DEFAULT ROLE 'wb_app' TO 'wb_app_user'@'localhost';
