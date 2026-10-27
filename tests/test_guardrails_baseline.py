"""The first version of the checks: escalation, grounded numbers, medical wording, output shape.
The five known weaknesses are tested in their own files (test_fix1 ... test_fix5)."""
import json

import pytest

from service.guardrails import escalation_needed, escalation_response, validate_output
from insight_helpers import SNAPSHOT, answer, snapshot


# ---------- escalation ----------
@pytest.mark.parametrize("last5, expected", [
    ([1, 2, 2, 4, 5], True),        # three low (2 or below) -> escalate
    ([2, 2, 2, 2, 2], True),
    ([1, 1, 5, 5, 5], False),       # only two low: the near-miss case, must NOT escalate
    ([3, 3, 3, 3, 3], False),
    ([], False),                    # no check-ins at all
])
def test_escalation_rule(last5, expected):
    assert escalation_needed(snapshot(mood={"last5": last5, "low_count": 0})) is expected


def test_escalation_counts_the_list_not_the_stored_low_count():
    # low_count says 0, but the list has three low values: the list wins
    assert escalation_needed(snapshot(mood={"last5": [1, 1, 1, 5, 5], "low_count": 0})) is True


def test_escalation_message_is_fixed_and_flagged():
    out = escalation_response(snapshot(mood={"last5": [1, 2, 2, 4, 5], "low_count": 3}))
    assert out["safety_flag"] is True and out["tone"] == "supportive"


# ---------- grounded numbers ----------
def test_valid_answer_is_accepted():
    out, problems = validate_output(answer("Your steps rose compared with your usual level this week."), SNAPSHOT)
    assert out is not None and problems == []


def test_invented_number_is_rejected():
    out, problems = validate_output(answer("Your steps changed by 37% this week."), SNAPSHOT)
    assert out is None and "not in the snapshot" in problems[0]


def test_number_with_the_sign_dropped_is_still_a_real_number():
    out, _ = validate_output(answer("Your active minutes changed by 16.3% this week."), SNAPSHOT)
    assert out is not None            # 16.3 is in the snapshot as -16.3


def test_action_goal_with_a_unit_is_allowed_but_a_bare_number_is_not():
    ok, _ = validate_output(answer("Your steps rose this week.", actions=["Walk for 25 minutes today.", "Sleep early."]), SNAPSHOT)
    bad, _ = validate_output(answer("Your steps rose this week.", actions=["Aim for 777 today.", "Sleep early."]), SNAPSHOT)
    assert ok is not None and bad is None


# ---------- medical wording ----------
def test_medical_wording_is_rejected():
    out, problems = validate_output(answer("You may have insomnia, so consider melatonin."), SNAPSHOT)
    assert out is None and "medical wording" in problems[0]


# ---------- output shape ----------
def test_not_json_is_rejected():
    out, problems = validate_output("Sure! Here is the insight", SNAPSHOT)
    assert out is None and "invalid JSON" in problems[0]


def test_json_inside_code_fences_is_accepted():
    raw = "```json\n" + answer("Your steps rose compared with your usual level this week.") + "\n```"
    assert validate_output(raw, SNAPSHOT)[0] is not None


def test_three_sentences_are_rejected():
    out, problems = validate_output(answer("One thing. Two things. Three things."), SNAPSHOT)
    assert out is None and "one or two sentences" in problems[0]


def test_unknown_tone_is_rejected():
    out, _ = validate_output(answer("Your steps rose this week.", tone="angry"), SNAPSHOT)
    assert out is None


def test_the_service_sets_member_id_and_safety_flag_not_the_model():
    raw = json.loads(answer("Your steps rose compared with your usual level this week."))
    raw["member_id"], raw["safety_flag"] = "M9999", True
    out, _ = validate_output(json.dumps(raw), SNAPSHOT)
    assert out["member_id"] == "M0042" and out["safety_flag"] is False
