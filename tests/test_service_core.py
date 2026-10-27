"""The flow in service/core.py with a fake model: escalation first, one retry, then the safe fallback."""
import json

import pytest

from service import core, db
from service.core import fallback_response, generate_insight
from service.guardrails import validate_output
from insight_helpers import SNAPSHOT, answer, snapshot

GOOD = answer("Your steps rose compared with your usual level this week.")
BAD = answer("Your steps changed by 37% this week.")          # 37 is not in the snapshot


class FakeClient:
    """Plays back a list of answers (or exceptions) and remembers what it was asked."""
    name, model = "fake", "fake-model"

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def chat(self, messages):
        self.calls.append(messages)
        reply = self.replies[len(self.calls) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def with_snapshot(monkeypatch):
    def use(snap):
        monkeypatch.setattr(db, "fetch_snapshot", lambda member_id: snap)
    return use


def test_good_answer_on_the_first_try(with_snapshot):
    with_snapshot(SNAPSHOT)
    client = FakeClient(GOOD)
    out = generate_insight("M0042", client)
    assert out["meta"]["source"] == "llm" and out["meta"]["attempts"] == 1 and len(client.calls) == 1


def test_escalation_never_calls_the_model(with_snapshot):
    with_snapshot(snapshot(mood={"last5": [1, 2, 2, 4, 5], "low_count": 3}))
    client = FakeClient(GOOD)
    out = generate_insight("M0042", client)
    assert out["safety_flag"] is True and out["meta"]["source"] == "escalation_template" and client.calls == []


def test_one_retry_and_the_reasons_are_sent_back(with_snapshot):
    with_snapshot(SNAPSHOT)
    client = FakeClient(BAD, GOOD)
    out = generate_insight("M0042", client)
    assert out["meta"]["source"] == "llm" and out["meta"]["attempts"] == 2
    assert "rejected" in client.calls[1][-1]["content"] and "37" in client.calls[1][-1]["content"]


def test_fallback_after_two_bad_answers_and_never_a_third_call(with_snapshot):
    with_snapshot(SNAPSHOT)
    client = FakeClient(BAD, BAD, GOOD)
    out = generate_insight("M0042", client)
    assert out["meta"]["source"] == "fallback" and len(client.calls) == 2


def test_fallback_when_the_model_is_down(with_snapshot):
    with_snapshot(SNAPSHOT)
    out = generate_insight("M0042", FakeClient(ConnectionError("down"), ConnectionError("down")))
    assert out["meta"]["source"] == "fallback" and out["safety_flag"] is False


@pytest.mark.parametrize("snap", [SNAPSHOT, snapshot(wearable=[
    {"metric": m, "avg_7d": None, "avg_30d": None, "change_pct": None}
    for m in ("steps", "active_minutes", "sleep_hours", "resting_hr")])])
def test_the_fallback_is_itself_a_valid_answer(snap):
    out, problems = validate_output(json.dumps(fallback_response(snap)), snap)
    assert out is not None, problems
