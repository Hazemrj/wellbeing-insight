"""What we send to the model.

Design choice: the CODE picks the facts worth talking about and writes them in the exact evidence format.
The model only writes friendly words around them. A small model is much more reliable at that than at
finding and calculating facts itself.
"""
from __future__ import annotations

import json

SYSTEM_PROMPT = """You are a friendly wellbeing coach inside a wellness app.
You write short, personal, safe coaching insights for ONE member, using ONLY the data given.

HARD RULES
1. Use only numbers that appear in the SNAPSHOT or FACTS. Never invent, estimate or calculate new numbers.
2. No medical content: no diagnoses, no named conditions, no medication or supplement advice, no words like "disorder" or "symptom".
3. Be kind and non-judgemental. Never shame the member. Do not mention risk scores, personas, groups or machine-learning labels.
4. Say a number went up only if it went up, and down only if it went down. Check the sign of the change.
5. Reply with ONE JSON object and nothing else."""

OUTPUT_SPEC = """Return exactly this JSON shape:
{
  "member_id": "<copy from snapshot>",
  "insight": "ONE or TWO short sentences about a trend in the member's data",
  "evidence": ["copy 1-2 lines from FACTS exactly as written"],
  "actions": ["small, specific action for this week", "second small, specific action"],
  "tone": "one of: encouraging | supportive | celebratory | neutral",
  "safety_flag": false
}
Evidence MUST be a JSON list (square brackets) of strings, copied character for character from FACTS. Keep the underscores in the names (active_minutes_7d, not "active minutes_7d").
Actions: exactly 2, each under 20 words, doable this week. If you mention an amount, attach a unit (e.g. "10 minutes")."""

WORDS = {"steps": "steps", "active_minutes": "active minutes", "sleep_hours": "sleep", "resting_hr": "resting heart rate"}


def _fmt(v):
    return "n/a" if v is None else str(v)


def key_signals(snap: dict, max_items: int = 3, min_abs_pct: float = 5.0) -> list[dict]:
    """The biggest changes of the 7-day average against the member's own 30-day average, as ready-to-copy lines."""
    items = []
    for w in snap["wearable"]:
        if w["avg_7d"] is not None and w["avg_30d"] is not None and w["change_pct"] is not None:
            if abs(w["change_pct"]) >= min_abs_pct:
                items.append(w)
    items.sort(key=lambda w: abs(w["change_pct"]), reverse=True)           # biggest change first
    out = []
    for w in items[:max_items]:
        # for resting heart rate a RISE is the worse direction, for the other three a FALL is worse
        worse = w["change_pct"] > 0 if w["metric"] == "resting_hr" else w["change_pct"] < 0
        out.append({
            "metric": w["metric"],
            "direction": "worse" if worse else "better",
            "went": "up" if w["change_pct"] > 0 else "down",
            "line": f"{w['metric']}_7d: {_fmt(w['avg_7d'])} vs baseline {_fmt(w['avg_30d'])} ({w['change_pct']:+.1f}%)",
        })
    return out


def suggest_tone(signals: list[dict]) -> str:
    worse = sum(1 for s in signals if s["direction"] == "worse")
    better = sum(1 for s in signals if s["direction"] == "better")
    if worse > better:
        return "supportive"
    if better > worse:
        return "celebratory" if better >= 2 else "encouraging"
    return "encouraging"


def compact_json(snap: dict) -> str:
    return json.dumps(snap, separators=(",", ":"), ensure_ascii=False)       # no spaces: fewer tokens


def build_messages(snap: dict, feedback: list[str] | None = None) -> list[dict]:
    signals = key_signals(snap)
    # With no big change there is still one real line to copy, so the model never copies a sentence as evidence.
    facts = "\n".join(f"- {s['line']}" for s in signals) or f"- app_streak_days: {snap['app']['streak_days']}"
    moves = "\n".join(f"- {WORDS[s['metric']]} went {s['went']} ({s['direction']} than usual)" for s in signals)
    user = (
        f"FACTS (you may copy these lines exactly):\n{facts}\n\n"
        f"WHAT THE FACTS MEAN:\n{moves or '- the week was close to the usual level, so keep the insight general and positive'}\n\n"
        f"Suggested tone: {suggest_tone(signals)}\n\n"
        f"SNAPSHOT:\n{compact_json(snap)}\n\n{OUTPUT_SPEC}"
    )
    if feedback:
        user += ("\n\nYour previous answer was rejected for these reasons - fix them and answer again:\n- "
                 + "\n- ".join(feedback))
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
