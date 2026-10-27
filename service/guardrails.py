"""All safety checks live here, in plain Python, not only in the prompt.

1. escalation_needed()  - repeated low mood -> fixed supportive message, the model is never called
2. check_grounding()    - every number in the answer must exist in the snapshot
3. check_no_medical()   - no diagnoses, conditions or medication advice
4. validate_output()    - JSON shape, lengths, allowed tone, plus the checks above
"""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError, field_validator

ALLOWED_TONES = {"encouraging", "supportive", "celebratory", "neutral"}
LOW_MOOD = 2                 # a check-in of 2 or below is "low"
LOW_MOOD_MIN_COUNT = 3       # 3 or more low check-ins among the last 5 -> escalate


# --------------------------------------------------------------------------
# 1. Escalation
# --------------------------------------------------------------------------
def escalation_needed(snapshot: dict) -> bool:
    """True when 3 or more of the last 5 check-ins (inside the last 14 days) are 2 or below.
    It counts the list itself and does not trust the precomputed mood.low_count."""
    checkins = (snapshot.get("mood") or {}).get("last5") or []
    return sum(1 for v in checkins if isinstance(v, (int, float)) and v <= LOW_MOOD) >= LOW_MOOD_MIN_COUNT


def escalation_response(snapshot: dict) -> dict:
    """Fixed wording written by a human. It has no diagnosis and no coaching tips."""
    values = ", ".join(str(v) for v in snapshot["mood"]["last5"])
    return {
        "member_id": snapshot["member_id"],
        "insight": "Your recent mood check-ins have been low, and that matters more than any step or sleep goal this week. "
                   "You don't have to work through this alone.",
        "evidence": [f"recent_mood_checkins: {values}"],
        "actions": [
            "Please consider talking with a qualified professional, such as your doctor or a counsellor, this week.",
            "Reach out to someone you trust, and use your company's confidential support service if you have one.",
        ],
        "tone": "supportive",
        "safety_flag": True,
    }


# --------------------------------------------------------------------------
# 2. Grounding: every number must come from the snapshot
# --------------------------------------------------------------------------
_NUM = re.compile(r"(?<![A-Za-z_\d.])-?\d[\d,]*(?:\.\d+)?")           # a number such as 47.4, -3, 9,200
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")                           # a date such as 2026-09-28
# In ACTIONS a number is a suggested goal ("walk 10 minutes"), not a claim about the member.
# It is allowed only when it is directly followed by a unit.
_ACTION_UNITS = r"(?:min(?:ute)?s?|hours?|hrs?|days?|nights?|times?|glass(?:es)?|steps?|breaks?)"
_ACTION_NUM = re.compile(rf"(?<![A-Za-z_\d.])\d[\d,]*(?:\.\d+)?(?=\s*-?\s*{_ACTION_UNITS}\b)", re.I)


# Arabic-Indic digits (٠-٩) and Eastern Arabic-Indic digits (۰-۹) become 0-9. The Arabic decimal separator ٫ becomes ".",
# the Arabic thousands separator ٬ becomes "," and the Arabic percent sign ٪ becomes "%".
_DIGIT_TABLE = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩" "۰۱۲۳۴۵۶۷۸۹" "٫٬٪",
    "0123456789" "0123456789" ".,%",
)


def normalize_digits(text: str) -> str:
    """Write every Arabic digit as a normal digit, so '٤٧٫٤' is checked exactly like '47.4'.
    This is only used for CHECKING. The text the member receives is not changed."""
    return text.translate(_DIGIT_TABLE)


def flatten_numbers(obj) -> list[float]:
    """Every number inside the snapshot (booleans excluded), plus the parts of its date strings."""
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        if _DATE.fullmatch(obj):                                      # "2026-09-28" -> 2026, 9, 28
            out += [float(x) for x in re.findall(r"\d+", obj)]
    elif isinstance(obj, dict):
        for v in obj.values():
            out += flatten_numbers(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out += flatten_numbers(v)
    return out


def _all_strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _all_strings(v)]
    if isinstance(obj, (list, tuple)):
        return [s for v in obj for s in _all_strings(v)]
    return []


def _decimals(token: str) -> int:
    return len(token.split(".")[1]) if "." in token else 0


def number_is_grounded(token: str, snapshot_numbers: list[float]) -> bool:
    """A token is fine if it equals a snapshot number (sign ignored, so 'down 16.3%' matches -16.3),
    or equals a snapshot number rounded to the token's own precision ('16%' matches 16.3)."""
    try:
        x = abs(float(token.replace(",", "")))
    except ValueError:
        return False
    nd = _decimals(token)
    for v in snapshot_numbers:
        if abs(v) == x or round(abs(v), nd) == round(x, nd):
            return True
    return False


def ungrounded_numbers(text: str, snapshot: dict, *, is_action: bool = False) -> list[str]:
    """The numbers in `text` that do not exist in the snapshot."""
    text = normalize_digits(text)                                          # Fix 5: Arabic digits become normal digits first
    allowed = flatten_numbers(snapshot)
    for d in (s for s in _all_strings(snapshot) if _DATE.fullmatch(s)):    # a date copied exactly from the snapshot is fine
        text = text.replace(d, " ")
    skip_spans: list[tuple[int, int]] = []
    if is_action:                                                          # suggested goals with a unit are allowed
        skip_spans = [m.span() for m in _ACTION_NUM.finditer(text)]
    bad = []
    for m in _NUM.finditer(text):
        if any(s <= m.start() < e for s, e in skip_spans):
            continue
        if not number_is_grounded(m.group(0), allowed):
            bad.append(m.group(0))
    return bad


def check_grounding(out: dict, snapshot: dict) -> list[str]:
    """A list of problems. An empty list means every number is grounded."""
    problems = []
    bad = ungrounded_numbers(out.get("insight", ""), snapshot)
    if bad:
        problems.append(f"insight contains numbers not in the snapshot: {bad}")
    for i, ev in enumerate(out.get("evidence", [])):
        bad = ungrounded_numbers(ev, snapshot)
        if bad:
            problems.append(f"evidence[{i}] contains numbers not in the snapshot: {bad}")
    for i, act in enumerate(out.get("actions", [])):
        bad = ungrounded_numbers(act, snapshot, is_action=True)
        if bad:
            problems.append(f"actions[{i}] contains numbers not in the snapshot: {bad}")
    return problems


# --------------------------------------------------------------------------
# 3. No medical claims (the first blocklist, widened in Fix 4)
# --------------------------------------------------------------------------
_MEDICAL_PATTERNS = [
    r"diagnos\w*", r"\bdepress\w*", r"\banxi\w*", r"\binsomnia\b", r"\bsleep apn\w*", r"\bhypertension\b",
    r"\bblood pressure\b", r"\bdiabet\w*", r"\bcardiac\b", r"\barrhythmia\b", r"\bheart (?:disease|condition|problem|attack)\b",
    r"\bdisorders?\b", r"\bsyndrome\b", r"\bcondition\b", r"\bdisease\b", r"\bclinical\w*", r"\bmedicat\w*",
    r"\bmedicine\b", r"\bprescri\w*", r"\bdos(?:e|age)\b", r"\bmg\b", r"\bsupplements?\b", r"\bmelatonin\b",
    r"\bantidepress\w*", r"\bcure\b", r"\btreat(?:ment|ing)?\b", r"\bsymptoms?\b", r"\bpainkillers?\b", r"\bpills?\b",
    # Fix 4: wording the first list missed. Mental health:
    r"\bburn(?:ed|t)?[- ]?out\b", r"\bmental (?:health|illness)\b", r"\btherap\w*", r"\bpsychiatr\w*", r"\bpsycholog\w*",
    r"\bcounsel(?:l)?(?:or|ors|ing|lor|lors)\b", r"\bpanic\b", r"\btrauma\w*", r"\bptsd\b", r"\badhd\b", r"\bbipolar\b",
    r"\bschizo\w*", r"\bsuicid\w*", r"\bself[- ]harm\w*", r"\bhopeless\w*",
    # Fix 4: other medical wording:
    r"\bdoctors?\b", r"\bphysicians?\b", r"\bnurses?\b", r"\bhospital\w*", r"\bmedical\b", r"\bobes\w*", r"\boverweight\b",
    r"\basthma\b", r"\bmigraines?\b", r"\bthyroid\b", r"\bcholesterol\b", r"\binflammat\w*", r"\bstroke\b", r"\bcancer\b",
    r"\bepilep\w*", r"\bchronic\b", r"\bvitamins?\b", r"\btablets?\b", r"\bantibiotics?\b", r"\bibuprofen\b",
    r"\bparacetamol\b", r"\baspirin\b", r"\bsedatives?\b", r"\bsteroids?\b", r"\boverdos\w*",
    r"\btachycardia\b", r"\bbradycardia\b", r"\bpalpitations?\b",
]
_MEDICAL_RE = re.compile("|".join(_MEDICAL_PATTERNS), re.I)


def check_no_medical(out: dict) -> list[str]:
    text = " ".join([out.get("insight", ""), *out.get("evidence", []), *out.get("actions", [])])
    hits = sorted({m.group(0).lower() for m in _MEDICAL_RE.finditer(text)})
    return [f"medical wording not allowed: {hits}"] if hits else []


# --------------------------------------------------------------------------
# 3b. Direction: the insight must not say a metric went up when it went down (Fix 1)
# --------------------------------------------------------------------------
# How a metric can be named in a sentence.
_METRIC_WORDS = {
    "steps":          r"\bsteps?\b|\bwalk(?:ing|ed)?\b",
    "active_minutes": r"\bactive\b|\bactivity\b|\bexercis\w*|\bworkouts?\b",
    "sleep_hours":    r"\bsleep\w*|\bslept\b",
    "resting_hr":     r"\bheart rate\b|\bresting (?:hr|pulse)\b|\bpulse\b",
}
# Words that say the NUMBER went up or down. ("up" and "down" count only in the forms below, so "keep up" is not a claim.)
_UP = re.compile(r"\b(?:rose|rise[sn]?|rising|increas\w*|higher|grew|grow(?:n|ing)?|climb\w*|jump\w*|gain\w*|above"
                 r"|up (?:by|\d)|(?:went|gone|is|are|was|were) up)\b", re.I)
_DOWN = re.compile(r"\b(?:fell|fall(?:s|en|ing)?|drop\w*|decreas\w*|declin\w*|lower|dip(?:s|ped)?|below|reduc\w*|slipp?\w*"
                   r"|down (?:by|\d)|(?:went|gone|is|are|was|were) down)\b", re.I)
# Words that say it got BETTER or WORSE. What is better depends on the metric (see _is_good).
_GOOD = re.compile(r"\b(?:improv\w*|better|healthier|stronger)\b", re.I)
_BAD = re.compile(r"\b(?:worse|worsen\w*|weaker|poorer)\b", re.I)
_NEGATION = re.compile(r"\b(?:not|no|never|without)\b|n't", re.I)
# Where one claim ends and the next begins.
_CLAUSE_SPLIT = re.compile(r"[.;!?,]|\b(?:but|while|whereas|although|though|yet|however)\b", re.I)


def _is_good(metric: str, change_pct: float) -> bool:
    """For steps, active minutes and sleep a rise is good. For resting heart rate a FALL is good."""
    return change_pct < 0 if metric == "resting_hr" else change_pct > 0


def _clauses(text: str) -> list[list[str]]:
    """Cut the text into small claims, so 'steps rose but sleep fell' is judged in two parts.
    Each claim is a list: normally one piece, but 'steps and sleep rose' gives two pieces that share the verb."""
    claims = []
    for part in _CLAUSE_SPLIT.split(text):
        pieces = re.split(r"\band\b", part)                     # split on 'and' only if both sides name a metric
        named = [any(re.search(rx, p, re.I) for rx in _METRIC_WORDS.values()) for p in pieces]
        claims.append(pieces if len(pieces) > 1 and all(named) else [part])
    return claims


def check_direction(out: dict, snapshot: dict) -> list[str]:
    problems = []
    change = {w["metric"]: w["change_pct"] for w in snapshot["wearable"]}
    for claim in _clauses(out.get("insight", "")):
        for i, piece in enumerate(claim):
            if _NEGATION.search(piece):                             # "did not drop" is not a claim we can judge
                continue
            words = piece
            if i < len(claim) - 1 and not (_UP.search(piece) or _DOWN.search(piece) or _GOOD.search(piece) or _BAD.search(piece)):
                words = claim[-1]                                   # 'steps and sleep rose': the first piece shares the last verb
            up, down = bool(_UP.search(words)), bool(_DOWN.search(words))
            good, bad = bool(_GOOD.search(words)), bool(_BAD.search(words))
            if up and down:                                         # both directions in one claim: too unclear to judge
                continue
            for metric, rx in _METRIC_WORDS.items():
                pct = change.get(metric)
                if pct is None or pct == 0 or not re.search(rx, piece, re.I):
                    continue
                if (up and pct < 0) or (down and pct > 0):
                    went = "fell" if pct < 0 else "rose"
                    problems.append(f"direction: the insight says {metric} went {'up' if up else 'down'} but it {went} ({pct:+}%)")
                if (good and not _is_good(metric, pct)) or (bad and _is_good(metric, pct)):
                    problems.append(f"direction: the insight says {metric} got {'better' if good else 'worse'} but it did not ({pct:+}%)")
    return problems


# --------------------------------------------------------------------------
# 3c. Evidence: a number must be the value of ITS OWN field (Fix 2)
# --------------------------------------------------------------------------
_NUMBER = r"-?[0-9][0-9,]*(?:\.[0-9]+)?"
# 'field: value', and for the wearable lines the extra  'vs baseline value (+x.x%)'  that prompt.py writes
_EVIDENCE_LINE = re.compile(
    rf"^(?P<field>[a-z0-9_ -]+):\s*(?P<value>{_NUMBER})"
    rf"(?:\s+vs baseline\s+(?P<base>{_NUMBER}))?"
    rf"(?:\s*\((?P<pct>[+-]?[0-9]+(?:\.[0-9]+)?)%\))?\s*$",
    re.I,
)


def evidence_fields(snapshot: dict) -> dict:
    """Every field an evidence line may talk about, with its true value from the snapshot."""
    fields = {}
    for w in snapshot["wearable"]:
        fields[f"{w['metric']}_7d"] = w["avg_7d"]
        fields[f"{w['metric']}_30d"] = w["avg_30d"]
    app = snapshot["app"]
    fields.update({
        "sync_rate_30d": snapshot["sync_rate_30d"],
        "app_opens_7d": app["opens_7d"], "app_opens_30d": app["opens_30d"],
        "days_since_last_open": app["days_since_last_open"],
        "app_streak_days": app["streak_days"], "active_streak_days": app["active_streak_days"],
        "mood_low_count": snapshot["mood"]["low_count"],
    })
    return fields


def _same_value(token: str, expected) -> bool:
    """Is the written number the expected one, at the precision it was written? (9200 equals 9200.0, 21 equals 20.7)"""
    if expected is None:
        return False
    nd = _decimals(token)
    return round(float(token.replace(",", "")), nd) == round(float(expected), nd)


def check_evidence_fields(out: dict, snapshot: dict) -> list[str]:
    problems = []
    fields = evidence_fields(snapshot)
    change = {w["metric"]: w["change_pct"] for w in snapshot["wearable"]}
    for i, line in enumerate(out.get("evidence", [])):
        m = _EVIDENCE_LINE.match(normalize_digits(line).strip())          # Fix 5: Arabic digits become normal digits first
        if not m:
            problems.append(f"evidence[{i}] must look like 'field: value', for example 'steps_7d: 9200.0', got: {line!r}")
            continue
        field = re.sub(r"[ -]+", "_", m.group("field").lower())            # Fix 6: 'Active minutes_7d' is 'active_minutes_7d'
        if field not in fields:
            problems.append(f"evidence[{i}]: unknown field {field!r}, use one of {sorted(fields)}")
            continue
        if not _same_value(m.group("value"), fields[field]):
            problems.append(f"evidence[{i}]: {field} is {fields[field]} in the snapshot, not {m.group('value')}")
        if m.group("base") is not None or m.group("pct") is not None:
            metric = field[:-3] if field.endswith("_7d") else None
            if metric not in change:
                problems.append(f"evidence[{i}]: 'vs baseline' and the percentage are only allowed on a *_7d wearable line")
                continue
            if m.group("base") is not None and not _same_value(m.group("base"), fields[f"{metric}_30d"]):
                problems.append(f"evidence[{i}]: the baseline of {metric} is {fields[f'{metric}_30d']}, not {m.group('base')}")
            if m.group("pct") is not None and not _same_value(m.group("pct"), change[metric]):
                problems.append(f"evidence[{i}]: the change of {metric} is {change[metric]:+}%, not {m.group('pct')}%")
    return problems


# --------------------------------------------------------------------------
# 3d. Prompt rules enforced in code: no personas, no risk scores, no machine-learning wording (Fix 3)
# --------------------------------------------------------------------------
_FORBIDDEN_PATTERNS = [
    # persona names and the word persona itself
    r"engaged achievers?", r"curious desk[- ]sitters?", r"irregular rhythms?", r"quiet drifters?",
    r"\bpersonas?\b", r"\bclusters?\b",
    # risk scores and bands
    r"\brisk (?:score|band|level|model|category|rating)\b", r"\b(?:high|medium|low)[- ]risk\b", r"\bat risk\b",
    r"\bdisengage\w*", r"\bchurn\w*",
    # machine-learning wording
    r"\bmachine[- ]learning\b", r"\bartificial intelligence\b", r"\balgorithms?\b", r"\bclassifier\b",
    r"\bpredict\w*", r"\bmodels?\b", r"\bneural\b", r"\bprobabilit\w*",
]
_FORBIDDEN_RE = re.compile("|".join(_FORBIDDEN_PATTERNS), re.I)
_FORBIDDEN_CAPS_RE = re.compile(r"\b(?:AI|ML)\b")              # only in capitals, so a normal word is never hit


def check_prompt_rules(out: dict) -> list[str]:
    text = " ".join([out.get("insight", ""), *out.get("evidence", []), *out.get("actions", [])])
    hits = {m.group(0).lower() for m in _FORBIDDEN_RE.finditer(text)}
    hits = sorted(hits | {m.group(0) for m in _FORBIDDEN_CAPS_RE.finditer(text)})
    return [f"wording not allowed (persona, risk score or machine learning): {hits}"] if hits else []


# --------------------------------------------------------------------------
# 4. Output validation
# --------------------------------------------------------------------------
class ViOutput(BaseModel):
    member_id: str
    insight: str = Field(min_length=10, max_length=300)
    evidence: list[str] = Field(min_length=1, max_length=3)
    actions: list[str] = Field(min_length=2, max_length=2)
    tone: str
    safety_flag: bool = False

    @field_validator("tone")
    @classmethod
    def _tone(cls, v):
        if v not in ALLOWED_TONES:
            raise ValueError(f"tone must be one of {sorted(ALLOWED_TONES)}")
        return v

    @field_validator("insight")
    @classmethod
    def _two_sentences(cls, v):
        n = len([s for s in re.split(r"(?<=[.!?])\s+", v.strip()) if s])
        if n > 2:
            raise ValueError("insight must be one or two sentences")
        return v

    @field_validator("evidence", "actions")
    @classmethod
    def _items(cls, v):
        for s in v:
            if not isinstance(s, str) or not s.strip() or len(s) > 160:
                raise ValueError("each list item must be a non-empty string of at most 160 characters")
        return v


def parse_json_loosely(raw: str) -> dict:
    """Models sometimes wrap the JSON in ```json fences or add chatter. Take the first {...} block."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found")
    return json.loads(text[start:end + 1])


def validate_output(raw: str, snapshot: dict) -> tuple[dict | None, list[str]]:
    """Returns (clean_output, problems). clean_output is None when anything failed."""
    try:
        data = parse_json_loosely(raw)
    except (ValueError, json.JSONDecodeError) as e:
        return None, [f"invalid JSON: {e}"]
    if not isinstance(data, dict):
        return None, ["JSON is not an object"]
    if isinstance(data.get("evidence"), str):            # Fix 7: evidence written as one text -> a list of lines
        data["evidence"] = [line.strip() for line in re.split(r"[\n;]+", data["evidence"]) if line.strip()]
    data["member_id"] = snapshot["member_id"]            # the service, not the model, decides identity ...
    data["safety_flag"] = False                          # ... and the safety flag
    try:
        out = ViOutput(**{k: data.get(k) for k in ViOutput.model_fields}).model_dump()
    except ValidationError as e:
        return None, [f"schema: {err['loc'][0]}: {err['msg']}" for err in e.errors()]
    problems = (check_grounding(out, snapshot) + check_no_medical(out)
                + check_direction(out, snapshot) + check_evidence_fields(out, snapshot) + check_prompt_rules(out))
    return (None, problems) if problems else (out, [])
