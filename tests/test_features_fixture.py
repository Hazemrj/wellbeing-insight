"""Hand-calculated test: the SQL features must equal the numbers worked out by hand in tests/fixtures/EXPECTED.md.

What the test does, in order:
  1. creates a SEPARATE database wellbeing_test (your real wellbeing is never touched)
  2. builds the tables and the procedure with the real scripts/migrate.py
  3. loads the 2-member, 14-day fixture (tests/fixtures/*.csv) into the raw tables
  4. runs the real cleaning step (sql/clean_daily_metrics.sql), so out-of-range values become NULL
  5. calls build_member_features('2026-09-14') and compares every feature with the hand-calculated value
  6. calls build_member_snapshots('2026-09-14') and compares each JSON snapshot with the same hand-calculated values

It needs an account that may create databases. It uses DB_USER and DB_PASSWORD, the same variables as migrate.py:
    set DB_USER=root
    set DB_PASSWORD=your_password
    python -m pytest tests/test_features_fixture.py -v
"""
import csv
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pymysql
import pytest
from pymysql.constants import CLIENT
from pymysql.cursors import DictCursor

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TEST_DB = "wellbeing_test"
AS_OF = "2026-09-14"
LOAD_ORDER = ["companies", "members", "raw_daily_metrics", "engagement", "mood_checkins"]   # parents first

D = Decimal
# Copied from tests/fixtures/EXPECTED.md (the hand calculation).
EXPECTED = {
    1: dict(avg_steps_7d=D("9200.0"), avg_steps_30d=D("7625.0"), steps_change_pct=D("20.7"),
            avg_active_7d=D("44.2"), avg_active_30d=D("39.2"), active_change_pct=D("12.6"),
            avg_sleep_7d=D("7.2"), avg_sleep_30d=D("7.1"), sleep_change_pct=D("0.7"),
            avg_hr_7d=D("61.3"), avg_hr_30d=D("61.5"), hr_change_pct=D("-0.2"),
            sync_rate_30d=D("0.929"),
            app_opens_7d=8, app_opens_30d=17, days_since_last_app_open=0, app_streak=5, active_streak=11,
            mood_last5=[5, 2, 2, 4, 1], mood_low_count=3),
    2: dict(avg_steps_7d=D("5000.0"), avg_steps_30d=D("4684.6"), steps_change_pct=D("6.7"),
            avg_active_7d=D("20.0"), avg_active_30d=D("20.0"), active_change_pct=D("0.0"),
            avg_sleep_7d=D("6.7"), avg_sleep_30d=D("6.8"), sleep_change_pct=D("-1.9"),
            avg_hr_7d=D("70.0"), avg_hr_30d=D("70.0"), hr_change_pct=D("0.0"),
            sync_rate_30d=D("0.929"),
            app_opens_7d=4, app_opens_30d=11, days_since_last_app_open=3, app_streak=0, active_streak=0,
            mood_last5=[2, 2], mood_low_count=2),
}


def connect(database=None):
    """Admin connection (can create databases). Multi statements on, so the cleaning file runs in one call."""
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"), port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "root"), password=os.environ.get("DB_PASSWORD", ""),
        database=database, charset="utf8mb4", client_flag=CLIENT.MULTI_STATEMENTS, cursorclass=DictCursor)


def load_fixture(cur):
    for table in LOAD_ORDER:
        with open(FIXTURES / f"{table}.csv", newline="") as f:
            reader = csv.reader(f)
            columns = next(reader)                                          # the header line = the column names
            rows = [[value if value != "" else None for value in row] for row in reader]   # empty cell = NULL
        placeholders = ", ".join(["%s"] * len(columns))
        cur.executemany(f"INSERT INTO `{table}` ({', '.join(columns)}) VALUES ({placeholders})", rows)


@pytest.fixture(scope="module")
def features():
    """Build the test database, return {member_id: feature row}, and drop the database afterwards."""
    admin = connect()
    admin.cursor().execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
    # Build the schema with the real migration script, pointed at the test database.
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "migrate.py")], capture_output=True, text=True,
                            env={**os.environ, "DB_NAME": TEST_DB})
    assert result.returncode == 0, result.stdout + result.stderr

    conn = connect(TEST_DB)
    cur = conn.cursor()
    load_fixture(cur)
    cur.execute((ROOT / "sql" / "clean_daily_metrics.sql").read_text(encoding="utf-8"))
    while cur.nextset():
        pass
    cur.execute("CALL build_member_features(%s)", (AS_OF,))
    conn.commit()
    cur.execute("SELECT * FROM member_features ORDER BY member_id")
    rows = {row["member_id"]: row for row in cur.fetchall()}
    yield conn, rows
    conn.close()
    admin.cursor().execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
    admin.close()


@pytest.mark.parametrize("member_id", [1, 2])
def test_features_equal_hand_calculation(features, member_id):
    _, rows = features
    row = rows[member_id]
    actual = {name: (json.loads(value) if name == "mood_last5" else value) for name, value in row.items()
              if name in EXPECTED[member_id]}
    wrong = {name: (actual[name], expected) for name, expected in EXPECTED[member_id].items() if actual[name] != expected}
    assert not wrong, f"member {member_id}: (SQL result, hand-calculated) -> {wrong}"


def test_out_of_range_and_unsynced_values_were_removed_by_cleaning(features):
    conn, _ = features
    cur = conn.cursor()
    cur.execute("SELECT member_id, metric_date, steps, resting_hr FROM daily_metrics "
                "WHERE (member_id = 1 AND metric_date = '2026-09-11') OR (member_id = 2 AND metric_date = '2026-09-14')")
    removed = {(r["member_id"], str(r["metric_date"])): r for r in cur.fetchall()}
    assert removed[(1, "2026-09-11")]["steps"] is None            # 150000 steps -> NULL
    assert removed[(2, "2026-09-14")]["resting_hr"] is None       # 220 bpm -> NULL


def test_calling_the_procedure_twice_does_not_duplicate_rows(features):
    conn, _ = features
    cur = conn.cursor()
    cur.execute("CALL build_member_features(%s)", (AS_OF,))
    cur.execute("SELECT COUNT(*) AS n FROM member_features")
    assert cur.fetchone()["n"] == 2


# ---------- snapshots ----------

def expected_snapshot(member_id, code):
    """The snapshot we expect, built from the same hand-calculated numbers as EXPECTED."""
    e = EXPECTED[member_id]
    return {
        "member_id": code,                                   # the external code, not the internal number
        "as_of": AS_OF,
        "wearable": [
            {"metric": "steps", "avg_7d": e["avg_steps_7d"], "avg_30d": e["avg_steps_30d"], "change_pct": e["steps_change_pct"]},
            {"metric": "active_minutes", "avg_7d": e["avg_active_7d"], "avg_30d": e["avg_active_30d"], "change_pct": e["active_change_pct"]},
            {"metric": "sleep_hours", "avg_7d": e["avg_sleep_7d"], "avg_30d": e["avg_sleep_30d"], "change_pct": e["sleep_change_pct"]},
            {"metric": "resting_hr", "avg_7d": e["avg_hr_7d"], "avg_30d": e["avg_hr_30d"], "change_pct": e["hr_change_pct"]},
        ],
        "sync_rate_30d": e["sync_rate_30d"],
        "app": {"opens_7d": e["app_opens_7d"], "opens_30d": e["app_opens_30d"],
                "days_since_last_open": e["days_since_last_app_open"],
                "streak_days": e["app_streak"], "active_streak_days": e["active_streak"]},
        "mood": {"last5": e["mood_last5"], "low_count": e["mood_low_count"]},
    }


@pytest.fixture(scope="module")
def snapshots(features):
    conn, _ = features
    cur = conn.cursor()
    cur.execute("CALL build_member_snapshots(%s)", (AS_OF,))
    conn.commit()
    cur.execute("SELECT member_id, CAST(snapshot AS CHAR) AS text FROM member_snapshots ORDER BY member_id")
    return conn, {row["member_id"]: row["text"] for row in cur.fetchall()}


@pytest.mark.parametrize("member_id, code", [(1, "M0001"), (2, "M0002")])
def test_snapshot_equals_hand_calculation(snapshots, member_id, code):
    _, texts = snapshots
    actual = json.loads(texts[member_id], parse_float=Decimal)     # numbers with a decimal point come back as exact Decimal
    assert actual == expected_snapshot(member_id, code)            # same keys, same values (key order does not matter)


def test_snapshot_is_compact_and_has_no_internal_id(snapshots):
    _, texts = snapshots
    for text in texts.values():
        assert len(text) / 4 < 1500                                # about 4 characters per token, token budget I set
        assert "member_id" in json.loads(text) and not str(json.loads(text)["member_id"]).isdigit()   # code like M0001, not 1


def test_building_snapshots_twice_does_not_duplicate_rows(snapshots):
    conn, _ = snapshots
    cur = conn.cursor()
    cur.execute("CALL build_member_snapshots(%s)", (AS_OF,))
    cur.execute("SELECT COUNT(*) AS n FROM member_snapshots")
    assert cur.fetchone()["n"] == 2
