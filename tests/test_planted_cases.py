"""Automated check: every planted escalation and near-miss member behaves as intended.

Test 1 and 2 check the patterns themselves (no database).
Test 3 asks MySQL, with a window function, about the data that is really loaded, so it does not trust the generator.
Run:  python -m pytest tests -v
"""
from pathlib import Path

import pandas as pd
import pytest

from db import connect
from generate_data import (AS_OF, ESCALATION_MIN_LOW, ESCALATION_WINDOW_CHECKINS, ESCALATION_WINDOW_DAYS,
                           LOW_MOOD, LOW_MOOD_PATTERNS, NEAR_MISS_PATTERNS, count_low)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

LAST_CHECKINS_SQL = """
WITH ranked AS (                                                   -- number each member's check-ins, newest = 1
  SELECT member_id, mood_score,
         ROW_NUMBER() OVER (PARTITION BY member_id ORDER BY checkin_date DESC) AS rn
  FROM mood_checkins
  WHERE checkin_date >  DATE_SUB(%s, INTERVAL %s DAY)              -- inside the 14 day window ...
    AND checkin_date <= %s                                         -- ... that ends on the as-of date
)
SELECT member_id, COUNT(*), SUM(mood_score <= %s)
FROM ranked
WHERE rn <= %s                                                     -- only the last 5 check-ins
GROUP BY member_id
"""


def test_escalation_patterns_have_three_low_in_last_five():
    for pattern in LOW_MOOD_PATTERNS:
        assert count_low(pattern[-ESCALATION_WINDOW_CHECKINS:]) >= ESCALATION_MIN_LOW, pattern


def test_near_miss_patterns_have_exactly_two_low_in_last_five():
    for pattern in NEAR_MISS_PATTERNS:
        assert count_low(pattern[-ESCALATION_WINDOW_CHECKINS:]) == 2, pattern


def test_loaded_database_matches_the_answer_key():
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT load_batch FROM raw_daily_metrics")
    batches = [row[0] for row in cur.fetchall()]
    if len(batches) != 1 or not (DATA_DIR / batches[0] / "ground_truth.csv").exists():
        pytest.skip("load a dataset first (scripts/load_data.py)")
    truth = pd.read_csv(DATA_DIR / batches[0] / "ground_truth.csv")           # load_batch = folder name, e.g. n500

    cur.execute(LAST_CHECKINS_SQL, (AS_OF, ESCALATION_WINDOW_DAYS, AS_OF, LOW_MOOD, ESCALATION_WINDOW_CHECKINS))
    counts = {member_id: (int(n), int(low)) for member_id, n, low in cur.fetchall()}
    conn.close()

    problems = []
    for row in truth.itertuples():
        n_checkins, n_low = counts.get(row.member_id, (0, 0))
        escalates = n_low >= ESCALATION_MIN_LOW
        if row.planted_escalation and not escalates:
            problems.append(f"{row.member_code}: planted escalation, but only {n_low} low in last {n_checkins}")
        elif row.planted_near_miss and not (n_low == 2 and n_checkins == ESCALATION_WINDOW_CHECKINS):
            problems.append(f"{row.member_code}: planted near-miss, but {n_low} low in last {n_checkins} (want 2 of 5)")
        elif not (row.planted_escalation or row.planted_near_miss) and escalates:
            problems.append(f"{row.member_code}: ordinary member meets the escalation rule by accident")
    assert not problems, "\n".join(problems)
