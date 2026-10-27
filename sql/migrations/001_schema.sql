CREATE DATABASE IF NOT EXISTS wellbeing
	CHARACTER SET UTF8MB4
    COLLATE utf8mb4_0900_ai_ci;
    

CREATE TABLE companies (												-- start defining the members table
	company_id	 SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,				-- surrogate key, 0-65,535 companies is enough
    name		 VARCHAR(100) NOT NULL,									-- synthetic company name, up to 100 characters, must exist (Arabic names fit in utf8mb4)
    country		 CHAR(2) NOT NULL,										-- always exactly 2 letters, so CHAR not VARCHAR
    created_date DATE NOT NULL,											-- the day the company became a client, a calendar day with no timestamp
	PRIMARY KEY (company_id),											-- uniquely identifies a company
    UNIQUE KEY uq_companies_name (name),								-- setting name as UNIQUE KEY, 2 companies cannot have the same name
    CONSTRAINT ck_companies_country CHECK (country IN ('AE','SA'))		-- country must only be AE or KA 
)	ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;	-- InnoDB for transactions and foreign keys, full Unicode text


CREATE TABLE members (													-- start defining the members table
	member_id 	 INT UNSIGNED NOT NULL AUTO_INCREMENT,					-- internal numeric key, 4 bytes
    member_code  CHAR(6) NOT NULL,										-- external id like M0042, the only id the insight service and the model ever see
    company_id 	 SMALLINT UNSIGNED NOT NULL,							-- which company the member belongs to, same type as companies.company_id
    age_band 	 ENUM('18-24', '25-34', '35-44', '45-54', '55+') NOT NULL, -- small fixed list, value must be from the listll)
	gender       ENUM('female', 'male', 'undisclosed') NOT NULL,        -- small fixed list
	job_type     ENUM('desk', 'field', 'shift') NOT NULL,               -- small fixed list
	join_date    DATE NOT NULL,                                         -- the day the member joined the platform
	PRIMARY KEY (member_id),                                            -- the primary key identifies a member row
	UNIQUE KEY uq_members_code (member_code),                           -- two members can never share a member code
	KEY idx_members_company (company_id),                               -- fast "all members of one company", also used by the foreign key
	CONSTRAINT fk_members_company FOREIGN KEY (company_id)              -- every member must point to a real company
		REFERENCES companies (company_id) ON DELETE RESTRICT            -- RESTRICT: a company that still has members cannot be deleted by accident
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;		-- same engine, character set and collation as every table



CREATE TABLE raw_daily_metrics (                                      -- start defining the raw wearable table
  member_id        INT UNSIGNED NOT NULL,                             -- which member the reading belongs to
  metric_date      DATE NOT NULL,                                     -- the member's local calendar day of the reading
  steps            INT NULL,                                          -- wide signed INT so even absurd values such as 150000 are stored, NULL if not sent
  active_minutes   INT NULL,                                          -- wide signed INT, no range check in the raw layer
  sleep_hours      DECIMAL(5,2) NULL,                                 -- exact decimal with room for wrong values like 23.5 or -1.0
  resting_hr       SMALLINT NULL,                                     -- signed SMALLINT so 0 or 220 bpm survive for audit
  wearable_synced  TINYINT(1) NOT NULL,                               -- 1 = the wearable synced that day, 0 = it did not (BOOLEAN is TINYINT(1))
  PRIMARY KEY (member_id, metric_date),                               -- exactly one raw row per member per day, a duplicate day is rejected loudly
  CONSTRAINT fk_raw_member FOREIGN KEY (member_id)                    -- a reading for an unknown member is useless, so reject it
    REFERENCES members (member_id) ON DELETE CASCADE                  -- CASCADE: erasing a member also erases their raw health data (privacy law)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;   -- same engine, character set and collation as every table


CREATE TABLE daily_metrics (                                          -- start defining the clean wearable table
  member_id        INT UNSIGNED NOT NULL,                             -- which member the day belongs to
  metric_date      DATE NOT NULL,                                     -- the calendar day
  steps            SMALLINT UNSIGNED NULL,                            -- 0..65535 fits the 0..60000 rule in 2 bytes, NULL means no valid value
  active_minutes   SMALLINT UNSIGNED NULL,                            -- 0..600 does not fit TINYINT (max 255) so SMALLINT, NULL means no valid value
  sleep_hours      DECIMAL(3,1) NULL,                                 -- exact one decimal place such as 7.3, never FLOAT, NULL means no valid value
  resting_hr       TINYINT UNSIGNED NULL,                             -- 30..120 bpm fits in one byte (0..255), NULL means no valid value
  wearable_synced  TINYINT(1) NOT NULL,                               -- 1 = synced, 0 = the wearable did not sync that day
  PRIMARY KEY (member_id, metric_date),                               -- one clean row per member per day, also serves "one member over a date range"
  CONSTRAINT fk_dm_member FOREIGN KEY (member_id)                     -- every clean row must belong to a real member
    REFERENCES members (member_id) ON DELETE CASCADE,                 -- CASCADE: erasing a member erases the clean rows too
  CONSTRAINT ck_dm_steps CHECK (steps BETWEEN 0 AND 60000),           -- a person cannot walk more than 60000 steps in a day (NULL passes a CHECK)
  CONSTRAINT ck_dm_active CHECK (active_minutes BETWEEN 0 AND 600),   -- more than 10 hours of activity is a sensor error
  CONSTRAINT ck_dm_sleep CHECK (sleep_hours BETWEEN 2.0 AND 14.0),    -- sleeping under 2 or over 14 hours is a sensor error
  CONSTRAINT ck_dm_hr CHECK (resting_hr BETWEEN 30 AND 120),          -- a living adult's resting heart rate is between 30 and 120 bpm
  CONSTRAINT ck_dm_synced CHECK (                                     -- a day that did not sync must carry no numbers at all
    wearable_synced = 1                                               -- either the wearable synced (any values, some may be NULL after cleaning)
    OR (steps IS NULL AND active_minutes IS NULL                      -- or it did not sync and steps and active minutes are NULL
        AND sleep_hours IS NULL AND resting_hr IS NULL))              -- and sleep and heart rate are NULL as well
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;   -- same engine, character set and collation as every table


CREATE TABLE engagement (                                             -- start defining the engagement table
  member_id         INT UNSIGNED NOT NULL,                            -- which member
  activity_date     DATE NOT NULL,                                    -- the calendar day of the app use
  app_opens         SMALLINT UNSIGNED NOT NULL DEFAULT 0,             -- how many times the app was opened, 0 is a real value so NOT NULL
  content_views     SMALLINT UNSIGNED NOT NULL DEFAULT 0,             -- how many articles or videos were viewed
  challenge_joined  TINYINT(1) NOT NULL DEFAULT 0,                    -- 1 if the member joined a challenge that day, else 0
  PRIMARY KEY (member_id, activity_date),                             -- one row per member per day
  CONSTRAINT fk_eng_member FOREIGN KEY (member_id)                    -- every row must belong to a real member
    REFERENCES members (member_id) ON DELETE CASCADE,                 -- CASCADE: erasing a member erases their app-use history
  CONSTRAINT ck_eng_opens CHECK (app_opens <= 500),                   -- more than 500 opens a day is a logging bug, not a person
  CONSTRAINT ck_eng_views CHECK (content_views <= 500),               -- same idea for content views
  CONSTRAINT ck_eng_challenge CHECK (challenge_joined IN (0, 1))      -- a TINYINT(1) could hold 127, this keeps it a true yes/no
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;   -- same engine, character set and collation as every table


CREATE TABLE mood_checkins (                                          -- start defining the mood table
  member_id     INT UNSIGNED NOT NULL,                                -- which member
  checkin_date  DATE NOT NULL,                                        -- the calendar day of the check-in
  mood_score    TINYINT UNSIGNED NOT NULL,                            -- 1 (very low) to 5 (very good), NOT NULL because a row only exists if there was a check-in
  PRIMARY KEY (member_id, checkin_date),                              -- the app allows one check-in per member per day
  CONSTRAINT fk_mood_member FOREIGN KEY (member_id)                   -- every check-in must belong to a real member
    REFERENCES members (member_id) ON DELETE CASCADE,                 -- CASCADE: erasing a member erases their mood data (the most sensitive kind)
  CONSTRAINT ck_mood_score CHECK (mood_score BETWEEN 1 AND 5)         -- only scores 1 to 5 are valid
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;   -- same engine, character set and collation as every table

