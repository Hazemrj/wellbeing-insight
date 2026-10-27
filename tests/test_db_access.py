"""Needs the real database: it checks the wb_app_user account from sql/roles.sql.
Skipped unless APP_DB_PASSWORD is set (and migrations 001-007, roles.sql and CALL build_member_snapshots were run).
    set APP_DB_PASSWORD=change_me_app
"""
import os

import pymysql
import pytest

from service import db

pytestmark = pytest.mark.skipif(not os.environ.get("APP_DB_PASSWORD"), reason="set APP_DB_PASSWORD to test the real database")


def test_reads_a_real_snapshot_as_wb_app_user():
    snap = db.fetch_snapshot("M0001")
    assert snap["member_id"] == "M0001" and len(snap["wearable"]) == 4


def test_unknown_member_is_not_found():
    with pytest.raises(db.MemberNotFound):
        db.fetch_snapshot("M9999")


def test_the_service_account_can_read_only_snapshots():
    conn = db.connect()
    cur = conn.cursor()
    with pytest.raises(pymysql.err.OperationalError) as e:        # error 1142 = SELECT denied
        cur.execute("SELECT COUNT(*) FROM members")
    assert e.value.args[0] == 1142
    with pytest.raises(pymysql.err.OperationalError):
        cur.execute("DELETE FROM member_snapshots")
    conn.close()
