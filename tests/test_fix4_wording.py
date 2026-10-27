"""Fix 4 - a wider wording check. The first version of the check blocked diagnosis and medication words but missed mental-health and
other medical wording. The words below were missed. The gaps that remain are written down in docs/GUARDRAILS.md."""
from pathlib import Path

import pytest

from service.guardrails import validate_output
from insight_helpers import SNAPSHOT, answer

DOCS = Path(__file__).resolve().parents[1] / "docs" / "GUARDRAILS.md"


def check(insight):
    out, problems = validate_output(answer(insight), SNAPSHOT)
    return problems if out is None else []


@pytest.mark.parametrize("insight", [
    "Signs of burnout; a therapist could help.",                           # an example of mental-health and medical wording
    "Your steps rose, but you seem to be burned out.",
    "Talking to a counsellor might help you.",
    "Talking to a counselor might help you.",
    "Consider seeing a psychologist about this.",
    "A psychiatrist could look at this pattern.",
    "Your mental health may be affected, even though your steps rose.",
    "You could be showing signs of panic attacks.",
    "You may be dealing with trauma.",
    "See a doctor before changing your routine.",
    "A nurse could check this for you.",
    "Please visit the hospital soon.",
    "This could be linked to obesity.",
    "A vitamin tablet may help your energy.",
    "Ibuprofen can help with that soreness.",
    "You may have asthma, or a thyroid problem.",
    "This looks like chronic fatigue.",
    "You may feel hopeless sometimes, even though your steps rose.",
    "Please call a suicide helpline.",
    "Your steps rose, but this could be self-harm related.",
])
def test_mental_health_and_medical_wording_is_rejected(insight):
    problems = check(insight)
    assert problems and "medical wording" in problems[0], insight


@pytest.mark.parametrize("insight", [
    "Your steps rose, and you stayed consistent this week.",
    "A short walk can ease everyday stress, and your steps rose.",          # 'stress' alone is normal coaching language
    "Great job, your steps rose and you kept a healthy routine.",
    "Try a calm evening routine, since your steps rose.",
])
def test_normal_coaching_language_is_still_accepted(insight):
    assert check(insight) == [], insight


def test_the_wording_is_checked_in_actions_and_evidence_too():
    out, problems = validate_output(answer("Your steps rose this week.", actions=["Book a therapy session.", "Sleep early."]), SNAPSHOT)
    assert out is None and "medical wording" in problems[0]


def test_the_gaps_that_remain_are_documented():
    text = DOCS.read_text(encoding="utf-8")
    assert "## Known gaps" in text
    gaps = text.split("## Known gaps", 1)[1]
    assert sum(1 for line in gaps.splitlines() if line.startswith("- ")) >= 5     # at least five gaps, one per bullet
