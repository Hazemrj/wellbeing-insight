"""Status codes of POST /insight: 200, 404 (unknown member), 422 (invalid input), 503 (database unavailable).
Also proves the SQL is parameterized. These tests need no database and no model."""
import pytest
from fastapi.testclient import TestClient

from service import app as app_module
from service import db
from service.llm import MockClient
from insight_helpers import SNAPSHOT

http = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def mock_model(monkeypatch):
    monkeypatch.setattr(app_module, "client", MockClient())       # never call a real model in these tests


def test_200_returns_an_insight(monkeypatch):
    monkeypatch.setattr(db, "fetch_snapshot", lambda member_id: SNAPSHOT)
    r = http.post("/insight", json={"member_id": "M0042"})
    body = r.json()
    assert r.status_code == 200
    assert body["member_id"] == "M0042" and body["meta"]["backend"] == "mock" and len(body["actions"]) == 2


def test_404_for_an_unknown_member(monkeypatch):
    def not_found(member_id):
        raise db.MemberNotFound(member_id)
    monkeypatch.setattr(db, "fetch_snapshot", not_found)
    r = http.post("/insight", json={"member_id": "M9999"})
    assert r.status_code == 404


@pytest.mark.parametrize("bad", [
    "M12", "m0042", "X0042", "M00421", "", " M0042",
    "M0042'; DROP TABLE members;--",          # an injection attempt
    "M٠٠٤٢",              # M followed by four Arabic-Indic digits
])
def test_422_for_an_invalid_member_id(monkeypatch, bad):
    def must_not_run(member_id):
        raise AssertionError("the database must not be touched for invalid input")
    monkeypatch.setattr(db, "fetch_snapshot", must_not_run)
    assert http.post("/insight", json={"member_id": bad}).status_code == 422


@pytest.mark.parametrize("body", [{}, {"member_id": 42}, {"member_id": None}, {"other": "M0042"}])
def test_422_for_a_missing_or_wrong_type_field(body):
    assert http.post("/insight", json=body).status_code == 422


def test_503_when_the_database_cannot_be_reached(monkeypatch):
    monkeypatch.setenv("APP_DB_PORT", "1")                        # nothing listens on port 1: a real refused connection
    r = http.post("/insight", json={"member_id": "M0042"})
    assert r.status_code == 503 and r.json()["detail"] == "database unavailable"


def test_503_when_a_query_fails(monkeypatch):
    def broken(member_id):
        raise db.DatabaseUnavailable("query failed")
    monkeypatch.setattr(db, "fetch_snapshot", broken)
    assert http.post("/insight", json={"member_id": "M0042"}).status_code == 503


# ---------- parameterized queries only ----------
class FakeCursor:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.log.append((sql, params))

    def fetchone(self):
        return ('{"member_id": "M0042"}',)


class FakeConnection:
    def __init__(self):
        self.log, self.closed = [], False

    def cursor(self):
        return FakeCursor(self.log)

    def close(self):
        self.closed = True


def test_the_member_code_is_sent_as_a_parameter_never_inside_the_sql(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(db, "connect", lambda: conn)
    db.fetch_snapshot("M0042")
    sql, params = conn.log[0]
    assert "%s" in sql and "M0042" not in sql          # the SQL text only has a placeholder
    assert params == ("M0042",)                        # the value travels separately
    assert conn.closed                                 # the connection is always closed
