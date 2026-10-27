"""Fix 5 - Arabic numerals. A model may write numbers with Arabic-Indic digits: 47.4 as ٤٧٫٤.
The grounding check must treat them exactly like 47.4."""
import pytest

from service import guardrails
from service.guardrails import validate_output
from insight_helpers import SNAPSHOT, answer


def problems_for(insight, evidence=None):
    out, problems = validate_output(answer(insight, evidence=evidence), SNAPSHOT)
    return problems if out is None else []


# ---------- the converter ----------
@pytest.mark.parametrize("written, expected", [
    ("٤٧٫٤", "47.4"),                    # Arabic-Indic digits with the Arabic decimal separator
    ("۴۷٫۴", "47.4"),                    # Eastern Arabic-Indic (Persian/Urdu) digits
    ("٩٬٢٠٠", "9,200"),                  # Arabic thousands separator
    ("٢٠٫٧٪", "20.7%"),                  # Arabic percent sign
    ("47.4", "47.4"),                    # normal digits are left alone
    ("Your steps rose ٢٠٫٧٪", "Your steps rose 20.7%"),
    ("", ""),
])
def test_normalize_digits(written, expected):
    assert guardrails.normalize_digits(written) == expected


# ---------- the check treats both forms the same ----------
@pytest.mark.parametrize("latin, arabic", [
    ("20.7", "٢٠٫٧"),       # a real number (steps change): both accepted
    ("9200.0", "٩٢٠٠٫٠"),   # a real number: both accepted
    ("8.5", "٨٫٥"),         # NOT in the snapshot, but its digit pieces 8 and 5 exist separately: both must be rejected
    ("37", "٣٧"),           # not in the snapshot: both rejected
])
def test_arabic_digits_get_the_same_verdict_as_latin_digits(latin, arabic):
    latin_problems = problems_for(f"Your steps rose by {latin}% this week.")
    arabic_problems = problems_for(f"Your steps rose by {arabic}% this week.")
    assert bool(arabic_problems) == bool(latin_problems), (latin_problems, arabic_problems)


def test_the_verdicts_themselves_are_right():
    assert problems_for("Your steps rose by ٢٠٫٧٪ this week.") == []                 # 20.7 is real
    assert problems_for("Your steps rose by ٨٫٥٪ this week.")                       # 8.5 is invented


def test_arabic_digits_in_an_evidence_line_are_checked_against_their_field():
    assert problems_for("Your steps rose this week.", evidence=["steps_7d: ٩٢٠٠٫٠"]) == []
    wrong = problems_for("Your steps rose this week.", evidence=["sleep_hours_7d: ٤٧٫٤"])    # 47.4 is the active-minutes value
    assert wrong and "sleep_hours_7d" in wrong[0]


def test_the_text_of_the_answer_is_not_changed():
    out, _ = validate_output(answer("Your steps rose by ٢٠٫٧٪ this week."), SNAPSHOT)
    assert "٢٠٫٧٪" in out["insight"]          # the member sees what the model wrote, we only normalize for checking
