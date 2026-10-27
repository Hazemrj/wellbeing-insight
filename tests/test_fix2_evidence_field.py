"""Fix 2 - the number belongs to its metric. Every evidence line is 'field: value', and the value must be the
value of THAT field in the snapshot, not just any number that exists somewhere in the snapshot.

In insight_helpers.SNAPSHOT the active-minutes 7-day average is 47.4 and the sleep 7-day average is 7.2.
"""
import pytest

from service.guardrails import validate_output
from insight_helpers import SNAPSHOT, answer

INSIGHT = "Your steps rose compared with your usual level this week."


def check(*evidence):
    out, problems = validate_output(answer(INSIGHT, evidence=list(evidence)), SNAPSHOT)
    return problems if out is None else []


def test_a_real_number_under_the_wrong_metric_is_rejected():
    problems = check("sleep_hours_7d: 47.4")             # 47.4 exists, but it is the ACTIVE MINUTES value
    assert problems and "sleep_hours_7d" in problems[0]


@pytest.mark.parametrize("line", [
    "steps_7d: 7625.0",                                  # that is the 30-day value of steps, not the 7-day value
    "steps_30d: 9200.0",                                 # and the other way round
    "steps_7d: 9200.0 vs baseline 56.6 (+20.7%)",        # baseline belongs to another metric
    "steps_7d: 9200.0 vs baseline 7625.0 (-16.3%)",      # the percentage belongs to active minutes
    "app_opens_7d: 17",                                  # 17 is the 30-day value
    "sync_rate_30d: 8",
])
def test_wrong_value_for_the_field_is_rejected(line):
    assert check(line), line


def test_unknown_field_name_is_rejected():
    problems = check("mood_score_7d: 5")
    assert problems and "unknown" in problems[0]


def test_a_line_that_is_not_field_colon_value_is_rejected():
    assert check("Your steps were 9200.0 this week")


@pytest.mark.parametrize("line", [
    "steps_7d: 9200.0 vs baseline 7625.0 (+20.7%)",      # the exact line the prompt gives the model
    "steps_7d: 9200",                                    # same number, written without .0
    "active_minutes_7d: 47.4 vs baseline 56.6 (-16.3%)",
    "sleep_hours_7d: 7.2",
    "resting_hr_30d: 61.5",
    "sync_rate_30d: 0.929",
    "app_opens_7d: 8",
    "app_opens_30d: 17",
    "days_since_last_open: 0",
    "app_streak_days: 5",
    "active_streak_days: 11",
    "mood_low_count: 0",
])
def test_correct_field_values_are_accepted(line):
    assert check(line) == [], line


def test_two_lines_are_each_checked():
    problems = check("steps_7d: 9200.0", "sleep_hours_7d: 47.4")
    assert len(problems) == 1 and "sleep_hours_7d" in problems[0]
