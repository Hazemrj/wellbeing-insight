"""The insight logic: get the snapshot, check escalation in code, ask the model, validate, retry once, fall back."""
from __future__ import annotations

import logging
import os
import time

from . import db
from .guardrails import escalation_needed, escalation_response, validate_output
from .prompt import build_messages, key_signals

log = logging.getLogger("insight")
MAX_ATTEMPTS = 2        # the first try plus ONE retry


def fallback_response(snap: dict) -> dict:
    """The safe answer when the model cannot give a valid one. Built from the snapshot by code, so it is always true."""
    signals = key_signals(snap, max_items=1)
    if signals:
        evidence = signals[0]["line"]
    else:
        evidence = f"app_streak_days: {snap['app']['streak_days']}"
    return {
        "member_id": snap["member_id"],
        "insight": "Here is your weekly check-in: small, steady habits add up, so keep going at a pace that feels good.",
        "evidence": [evidence],
        "actions": ["Take a short walk after one meal today.", "Pick a regular bedtime and keep it for the next few nights."],
        "tone": "encouraging",
        "safety_flag": False,
    }


def generate_insight(member_id: str, client) -> dict:
    t0 = time.perf_counter()
    snap = db.fetch_snapshot(member_id)          # may raise MemberNotFound or DatabaseUnavailable, the API handles both
    meta = {"source": None, "attempts": 0, "backend": getattr(client, "name", "?"),
            "model": getattr(client, "model", None), "problems": []}

    if escalation_needed(snap):                  # guardrail 1: decided in code, BEFORE and INSTEAD of the model
        out = escalation_response(snap)
        meta["source"] = "escalation_template"
    else:
        feedback = None
        out = None
        keep_rejected = os.environ.get("KEEP_REJECTED") == "1"          # off by default, only for evaluation
        for attempt in range(1, MAX_ATTEMPTS + 1):
            meta["attempts"] = attempt
            raw = None
            try:
                raw = client.chat(build_messages(snap, feedback))
                out, problems = validate_output(raw, snap)
            except Exception as e:               # network error, timeout, model not found ...
                out, problems = None, [f"model call failed: {type(e).__name__}"]
            if out is not None:
                meta["source"] = "llm"
                break
            meta["problems"] += problems
            if keep_rejected:
                meta.setdefault("rejected", []).append(raw)                # the raw text the checker refused
            feedback = problems                  # the retry tells the model what was wrong
            log.warning("member=%s attempt=%d rejected: %s", member_id, attempt, problems)
        if out is None:
            out = fallback_response(snap)
            meta["source"] = "fallback"

    meta["latency_ms"] = round((time.perf_counter() - t0) * 1000)
    log.info("member=%s source=%s attempts=%d latency_ms=%d", member_id, meta["source"], meta["attempts"], meta["latency_ms"])
    return {**out, "meta": meta}
