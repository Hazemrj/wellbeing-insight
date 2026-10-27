"""Fix 1 - direction check. An insight must not say a metric rose or improved when it fell, or the reverse.

In insight_helpers.SNAPSHOT: steps went UP 20.7%, active minutes went DOWN 16.3%, sleep went up 1.4%,
resting heart rate went down 0.3% (for resting heart rate, down is the good direction).
"""
import pytest

from service.guardrails import validate_output
from insight_helpers import SNAPSHOT, answer, snapshot


def check(insight):
    """Returns the list of problems (empty = the insight was accepted)."""
    out, problems = validate_output(answer(insight), SNAPSHOT)
    return problems if out is None else []


def test_says_rose_when_it_fell():
    problems = check("Your active minutes rose 16.3% this week.")
    assert problems and "active_minutes" in problems[0]


@pytest.mark.parametrize("insight", [
    "Your active minutes increased compared with your usual level.",
    "Your active minutes went up this week.",
    "Your steps dropped this week.",
    "Your steps fell compared with your usual level.",
    "Your steps are down by 20.7% this week.",
])
def test_wrong_direction_is_rejected(insight):
    assert check(insight), insight


@pytest.mark.parametrize("insight", [
    "Your active minutes improved this week.",             # they fell, so they did not improve
    "Your active minutes are doing better than usual.",
    "Your sleep got worse compared with your usual level.",   # sleep went up, so it did not get worse
])
def test_wrong_quality_word_is_rejected(insight):
    assert check(insight), insight


def test_resting_heart_rate_improves_when_it_goes_down():
    assert check("Your resting heart rate improved a little this week.") == []     # it went down: good
    hr_up = snapshot(wearable=[dict(w, avg_7d=62.5, change_pct=1.6) if w["metric"] == "resting_hr" else w
                               for w in SNAPSHOT["wearable"]])
    out, problems = validate_output(answer("Your resting heart rate improved a little this week."), hr_up)
    assert out is None and "resting_hr" in problems[0]


@pytest.mark.parametrize("insight", [
    "Your steps rose 20.7% this week.",
    "Your steps climbed compared with your usual level.",
    "Your active minutes fell 16.3% this week.",
    "Your active minutes are below your usual level.",
    "Your steps rose but your active minutes fell.",
    "Your steps rose, while your active minutes dropped.",
    "Your steps rose and your active minutes fell.",
    "Your steps and sleep both rose this week.",
    "Keep up the good work with your steps this week.",       # 'up' here is not a claim about the data
])
def test_true_claims_are_accepted(insight):
    assert check(insight) == [], insight


def test_each_metric_is_judged_on_its_own_part_of_the_sentence():
    problems = check("Your steps fell but your active minutes rose.")             # both halves are wrong
    assert any("steps" in p for p in problems) and any("active_minutes" in p for p in problems)


def test_a_negated_claim_is_not_judged():
    # "did not drop" is not a claim of direction. The check skips sentences with a negation (documented gap).
    assert check("Your steps did not drop this week.") == []


def test_a_claim_about_one_metric_is_not_judged_by_the_verb_of_another():
    # steps are steady (no direction word), only sleep "fell" ... but sleep really rose, so ONLY sleep is wrong
    problems = check("Your steps looked steady, and your sleep fell.")
    assert len(problems) == 1 and "sleep_hours" in problems[0]
