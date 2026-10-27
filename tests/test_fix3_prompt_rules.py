"""Fix 3 - prompt rules enforced in code. The prompt tells the model: do not mention personas, risk scores or
machine learning. A prompt is only a request, so the same rules are checked in code on every answer."""
import pytest

from service.guardrails import validate_output
from insight_helpers import SNAPSHOT, answer


def check(insight, actions=None):
    out, problems = validate_output(answer(insight, actions=actions), SNAPSHOT)
    return problems if out is None else []


@pytest.mark.parametrize("insight", [
    "Your steps rose, which is typical for our Engaged Achievers.",
    "As one of the Quiet Drifters, your steps rose this week.",
    "Members like the Curious Desk-Sitters often see their steps rise.",
    "People in the Irregular Rhythms group see their steps rise.",
    "Your persona suggests that your steps rose this week.",
    "You belong to a cluster of members whose steps rose.",
])
def test_persona_names_are_rejected(insight):
    problems = check(insight)
    assert problems and "not allowed" in problems[0], insight


@pytest.mark.parametrize("insight", [
    "Your steps rose, and your risk score is low.",
    "Your disengagement risk is high even though your steps rose.",
    "You are in the high risk band, but your steps rose.",
    "You are at high risk of dropping off, even though your steps rose.",
    "Your churn probability is small and your steps rose.",
])
def test_risk_scores_are_rejected(insight):
    assert check(insight), insight


@pytest.mark.parametrize("insight", [
    "Our machine learning model says your steps rose this week.",
    "Our machine-learning system noticed your steps rose.",
    "An algorithm noticed that your steps rose this week.",
    "The AI predicts your steps will keep rising.",
    "Our classifier shows your steps rose this week.",
    "Our prediction is that your steps will rise.",
])
def test_machine_learning_wording_is_rejected(insight):
    assert check(insight), insight


def test_the_rules_apply_to_the_actions_too():
    assert check("Your steps rose this week.", actions=["Keep your risk score low.", "Sleep well."])


@pytest.mark.parametrize("insight", [
    "Your steps rose compared with your usual level this week.",
    "Great progress, your steps rose and you stayed consistent.",
    "You are building a steady rhythm, and your steps rose.",      # 'rhythm' alone is a normal word
    "There is little risk in a short walk, and your steps rose.",   # the word 'risk' alone is not forbidden
    "Your modelling of a daily walk is great, and your steps rose.",  # 'model' is only forbidden as a whole word
])
def test_normal_coaching_language_is_accepted(insight):
    assert check(insight) == [], insight
