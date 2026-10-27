"""Small helpers shared by the insight service tests: a known snapshot and a way to build a model answer."""
import copy
import json

# One member, every number chosen by hand. Same shape as the snapshots that MySQL builds (migration 005).
SNAPSHOT = {
    "member_id": "M0042",
    "as_of": "2026-09-28",
    "wearable": [
        {"metric": "steps",          "avg_7d": 9200.0, "avg_30d": 7625.0, "change_pct": 20.7},    # went UP
        {"metric": "active_minutes", "avg_7d": 47.4,   "avg_30d": 56.6,   "change_pct": -16.3},   # went DOWN
        {"metric": "sleep_hours",    "avg_7d": 7.2,    "avg_30d": 7.1,    "change_pct": 1.4},     # went up a little
        {"metric": "resting_hr",     "avg_7d": 61.3,   "avg_30d": 61.5,   "change_pct": -0.3},    # went down a little
    ],
    "sync_rate_30d": 0.929,
    "app": {"opens_7d": 8, "opens_30d": 17, "days_since_last_open": 0, "streak_days": 5, "active_streak_days": 11},
    "mood": {"last5": [5, 4, 4, 3, 5], "low_count": 0},
}

GOOD_EVIDENCE = ["steps_7d: 9200.0 vs baseline 7625.0 (+20.7%)"]
GOOD_ACTIONS = ["Take a 10 minute walk after one meal on three days.",
                "Pick a regular bedtime and keep it for the next few nights."]


def snapshot(**changes):
    """A fresh copy of the snapshot. snapshot(mood={"last5": [1, 2, 2, 4, 5], "low_count": 3}) changes one part."""
    snap = copy.deepcopy(SNAPSHOT)
    snap.update(changes)
    return snap


def answer(insight, evidence=None, actions=None, tone="encouraging"):
    """The text a model would send back: one JSON object."""
    return json.dumps({
        "member_id": "M0042",
        "insight": insight,
        "evidence": GOOD_EVIDENCE if evidence is None else evidence,
        "actions": GOOD_ACTIONS if actions is None else actions,
        "tone": tone,
        "safety_flag": False,
    }, ensure_ascii=False)
