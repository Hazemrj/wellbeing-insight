# Hand-calculated expected features

Fixture: 2 members, 14 days (2026-09-01 = day 1 ... 2026-09-14 = day 14). Features are calculated **as of 2026-09-14**.
The numbers in `tests/test_features_fixture.py` are copied from this file.

## Rules used

| Rule | Meaning |
|---|---|
| 7-day window | day 14 and the 6 days before it = days 8 to 14 |
| 30-day window | day 14 and the 29 days before it. Only 14 days exist, so it covers days 1 to 14 |
| 14-day mood window | check-ins from 2026-09-01 to 2026-09-14. A check-in on 2026-08-31 is outside |
| Cleaning first | a value outside its range becomes NULL: steps 0-60000, active 0-600, sleep 2-14, resting HR 30-120. An unsynced day has all four values NULL |
| Averages | NULL days are ignored: sum of the real values divided by how many real values there are |
| % change | (7-day average - 30-day average) / 30-day average x 100, using the **unrounded** averages |
| Rounding | only at the end: averages and % change to 1 decimal, sync rate to 3 decimals (half rounds up) |
| App streak | consecutive days up to day 14 with at least 1 app open |
| Active streak | consecutive days up to day 14 with 30 or more active minutes. Days with no active-minutes value (unsynced) are skipped, they neither count nor break the streak. A synced day under 30 breaks it |

## Member 1 (M0001)

Planted problems: **day 10 is unsynced** (all values NULL) and **day 11 has steps = 150000** (out of range, becomes NULL; the other three values on day 11 are fine).

| Day | steps | active | sleep | HR | synced |
|---|---|---|---|---|---|
| 1 | 5000 | 20 | 7.0 | 60 | 1 |
| 2 | 6000 | 25 | 7.5 | 61 | 1 |
| 3 | 5500 | 30 | 6.5 | 62 | 1 |
| 4 | 7000 | 35 | 8.0 | 60 | 1 |
| 5 | 6500 | 40 | 7.0 | 63 | 1 |
| 6 | 7500 | 45 | 7.5 | 61 | 1 |
| 7 | 8000 | 50 | 6.0 | 64 | 1 |
| 8 | 9000 | 55 | 7.0 | 60 | 1 |
| 9 | 8500 | 60 | 7.5 | 62 | 1 |
| 10 | NULL | NULL | NULL | NULL | 0 |
| 11 | ~~150000~~ NULL | 40 | 8.0 | 61 | 1 |
| 12 | 9500 | 35 | 7.0 | 63 | 1 |
| 13 | 10000 | 30 | 6.5 | 62 | 1 |
| 14 | 9000 | 45 | 7.0 | 60 | 1 |

| Feature | Working | Expected |
|---|---|---|
| avg_steps_7d | days 8,9,12,13,14 (10 unsynced, 11 removed): 9000+8500+9500+10000+9000 = 46000; 46000 / 5 | **9200.0** |
| avg_steps_30d | days 1-9: 5000+6000+5500+7000+6500+7500+8000+9000+8500 = 63000; days 12-14: 9500+10000+9000 = 28500; 91500 / 12 days | **7625.0** |
| steps_change_pct | (9200 - 7625) / 7625 x 100 = 20.6557 | **20.7** |
| avg_active_7d | days 8,9,11,12,13,14: 55+60+40+35+30+45 = 265; 265 / 6 = 44.1667 | **44.2** |
| avg_active_30d | days 1-9: 20+25+30+35+40+45+50+55+60 = 360; days 11-14: 40+35+30+45 = 150; 510 / 13 = 39.2308 | **39.2** |
| active_change_pct | (44.1667 - 39.2308) / 39.2308 x 100 = 12.5817 | **12.6** |
| avg_sleep_7d | days 8,9,11,12,13,14: 7.0+7.5+8.0+7.0+6.5+7.0 = 43.0; 43.0 / 6 = 7.1667 | **7.2** |
| avg_sleep_30d | days 1-9: 64.0; days 11-14: 8.0+7.0+6.5+7.0 = 28.5; 92.5 / 13 = 7.1154 | **7.1** |
| sleep_change_pct | (7.1667 - 7.1154) / 7.1154 x 100 = 0.7207 | **0.7** |
| avg_hr_7d | days 8,9,11,12,13,14: 60+62+61+63+62+60 = 368; 368 / 6 = 61.3333 | **61.3** |
| avg_hr_30d | days 1-9: 60+61+62+60+63+61+64+60+62 = 553; days 11-14: 61+63+62+60 = 246; 799 / 13 = 61.4615 | **61.5** |
| hr_change_pct | (61.3333 - 61.4615) / 61.4615 x 100 = -0.2086 | **-0.2** |
| sync_rate_30d | 13 synced days (all but day 10) / 14 days = 0.92857 | **0.929** |

App opens per day, days 1 to 14: 2, 0, 1, 3, 0, 2, 1, 1, 0, 2, 1, 1, 2, 1

| Feature | Working | Expected |
|---|---|---|
| app_opens_7d | days 8-14: 1+0+2+1+1+2+1 | **8** |
| app_opens_30d | days 1-7: 2+0+1+3+0+2+1 = 9; plus 8 | **17** |
| days_since_last_app_open | day 14 has 1 open, so the last open is day 14 itself: 14 - 14 | **0** |
| app_streak | days 14,13,12,11,10 all have opens; day 9 has 0 and stops it | **5** |
| active_streak | day 14 (45), 13 (30, exactly 30 counts), 12 (35), 11 (40), day 10 skipped (unsynced), 9 (60), 8 (55), 7 (50), 6 (45), 5 (40), 4 (35), 3 (30); day 2 is 25 and stops it. Counted days: 14,13,12,11,9,8,7,6,5,4,3 | **11** |

Mood check-ins: day 2 = 3, day 5 = 2, day 8 = 1, day 9 = 4, day 11 = 2, day 12 = 2, day 14 = 5.

| Feature | Working | Expected |
|---|---|---|
| mood_last5 | newest 5, newest first: day 14 = 5, day 12 = 2, day 11 = 2, day 9 = 4, day 8 = 1 (day 5 is the 6th, so it is left out) | **[5, 2, 2, 4, 1]** |
| mood_low_count | values 2 or below among those 5: 2, 2, 1 | **3** |

## Member 2 (M0002)

Planted problems: **day 3 is unsynced** and **day 14 has resting HR = 220** (out of range, becomes NULL).
Steps are 4000 on day 1 and grow by 100 each day (5300 on day 14). Active minutes are 20 every day. Sleep is 7.0 every day except 5.0 on day 13. Resting HR is 70 every day except 220 on day 14.

| Feature | Working | Expected |
|---|---|---|
| avg_steps_7d | days 8-14: 4700+4800+4900+5000+5100+5200+5300 = 35000; 35000 / 7 | **5000.0** |
| avg_steps_30d | days 1-14 sum = 14 x 4650 = 65100; minus day 3 (4200, unsynced) = 60900; 60900 / 13 = 4684.6154 | **4684.6** |
| steps_change_pct | (5000 - 4684.6154) / 4684.6154 x 100 = 6.7323 | **6.7** |
| avg_active_7d | 7 days x 20 = 140; 140 / 7 | **20.0** |
| avg_active_30d | 13 synced days x 20 = 260; 260 / 13 | **20.0** |
| active_change_pct | (20 - 20) / 20 x 100 | **0.0** |
| avg_sleep_7d | days 8-14: 6 x 7.0 + 5.0 = 47.0; 47.0 / 7 = 6.7143 | **6.7** |
| avg_sleep_30d | 13 synced days: 12 x 7.0 + 5.0 = 89.0; 89.0 / 13 = 6.8462 | **6.8** |
| sleep_change_pct | (6.7143 - 6.8462) / 6.8462 x 100 = -1.9262 | **-1.9** |
| avg_hr_7d | days 8-13 (day 14 removed): 6 x 70 = 420; 420 / 6 | **70.0** |
| avg_hr_30d | days 1,2,4-13 = 12 days x 70 = 840; 840 / 12 | **70.0** |
| hr_change_pct | (70 - 70) / 70 x 100 | **0.0** |
| sync_rate_30d | 13 synced days / 14 days = 0.92857 | **0.929** |

App opens: 1 on each of days 1 to 11, then 0 on days 12, 13 and 14.

| Feature | Working | Expected |
|---|---|---|
| app_opens_7d | days 8,9,10,11 have 1 each | **4** |
| app_opens_30d | days 1-11 | **11** |
| days_since_last_app_open | last open was day 11; 14 - 11 | **3** |
| app_streak | day 14 has 0 opens, so the streak is already broken | **0** |
| active_streak | day 14 has 20 minutes (under 30) | **0** |

Mood check-ins: 2026-08-31 = 1, 2026-09-02 = 2, 2026-09-03 = 2.

| Feature | Working | Expected |
|---|---|---|
| mood_last5 | the 08-31 check-in is outside the 14-day window (window starts 09-01), so only 09-03 = 2 and 09-02 = 2 count, newest first | **[2, 2]** |
| mood_low_count | both are 2 or below (if 08-31 had wrongly counted this would be 3) | **2** |
