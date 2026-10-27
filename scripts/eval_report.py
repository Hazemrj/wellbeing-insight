"""Evaluation step 2 of 3: compare YOUR labels with the checker and write reports/eval/EVAL_REPORT.md.

    python scripts/eval_report.py --truth data/n500/ground_truth.csv

Needs reports/eval/responses.json (from eval_run.py) and reports/eval/labels.csv with every row filled in:
    all_claims_true = yes   every claim in the answer is true for that member's data
    all_claims_true = no    at least one claim is false or misleading (write which one in the note column)
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from service import db                                                    # noqa: E402
from service.guardrails import escalation_needed, validate_output         # noqa: E402

ANSWER_KEYS = ("member_id", "insight", "evidence", "actions", "tone", "safety_flag")


def checker_verdict(item: dict) -> tuple[bool, list[str]]:
    """The same checker the service uses, run again on the final answer. Returns (passed, problems)."""
    snap, resp = item["snapshot"], item["response"]
    if resp["meta"]["source"] == "escalation_template":
        # the template is fixed text, so the check is: the rule really holds and the evidence shows the real check-ins
        expected = [f"recent_mood_checkins: {', '.join(str(v) for v in snap['mood']['last5'])}"]
        problems = []
        if not escalation_needed(snap):
            problems.append("escalated but the snapshot does not meet the rule")
        if resp["evidence"] != expected or resp["safety_flag"] is not True:
            problems.append("evidence or safety_flag does not match the snapshot")
        return not problems, problems
    out, problems = validate_output(json.dumps({k: resp[k] for k in ANSWER_KEYS}), snap)
    return out is not None, problems


def read_labels(path: Path, codes: list[str]) -> dict:
    rows = {r["member_code"]: r for r in csv.DictReader(path.open(encoding="utf-8"))}
    labels = {}
    for code in codes:
        value = (rows.get(code, {}).get("all_claims_true") or "").strip().lower()
        if value not in ("yes", "no"):
            sys.exit(f"labels.csv: {code} has no yes/no label yet. Label all {len(codes)} members first.")
        labels[code] = {"label": value == "yes", "note": rows[code].get("note", "")}
    return labels


def percentile95(values: list[float]) -> float:
    return float(np.percentile(values, 95))          # linear interpolation between the two nearest values


def confusion(pred, truth) -> dict:
    pred, truth = np.array(pred, dtype=bool), np.array(truth, dtype=bool)
    tp, fp = int((pred & truth).sum()), int((pred & ~truth).sum())
    fn, tn = int((~pred & truth).sum()), int((~pred & ~truth).sum())
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "accuracy": (tp + tn) / max(1, tp + fp + fn + tn),
            "precision": tp / max(1, tp + fp), "recall": tp / max(1, tp + fn)}


def all_snapshots() -> list[dict]:
    """Every snapshot of the newest date, read as wb_app_user."""
    conn = db.connect()
    cur = conn.cursor()
    cur.execute("SELECT snapshot FROM member_snapshots WHERE as_of = (SELECT MAX(as_of) FROM member_snapshots)")
    rows = [json.loads(r[0]) for r in cur.fetchall()]
    conn.close()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", required=True)
    ap.add_argument("--dir", default=str(ROOT / "reports" / "eval"))
    args = ap.parse_args()
    folder = Path(args.dir)
    items = json.loads((folder / "responses.json").read_text(encoding="utf-8"))
    truth = pd.read_csv(args.truth).set_index("member_code")
    labels = read_labels(folder / "labels.csv", [i["member_code"] for i in items])
    n = len(items)

    # ---- checker versus my labels ----
    rows, disagreements = [], []
    for item in items:
        passed, problems = checker_verdict(item)
        mine = labels[item["member_code"]]
        rows.append((passed, mine["label"]))
        if passed != mine["label"]:
            disagreements.append((item, passed, problems, mine))
    agree = sum(1 for p, m in rows if p == m)
    both_ok = sum(1 for p, m in rows if p and m)
    checker_ok_me_no = sum(1 for p, m in rows if p and not m)       # the checker let a false claim through
    checker_no_me_ok = sum(1 for p, m in rows if not p and m)       # the checker blocked a true answer

    # ---- valid JSON ----
    final_valid = sum(1 for i in items if all(k in i["response"] for k in ANSWER_KEYS))
    model_items = [i for i in items if i["response"]["meta"]["source"] != "escalation_template"]
    calls = sum(i["response"]["meta"]["attempts"] for i in model_items)
    bad_json = sum(1 for i in model_items for p in i["response"]["meta"]["problems"] if p.startswith("invalid JSON"))
    failed_calls = sum(1 for i in model_items for p in i["response"]["meta"]["problems"] if p.startswith("model call failed"))
    first_try = sum(1 for i in model_items if i["response"]["meta"]["source"] == "llm" and i["response"]["meta"]["attempts"] == 1)
    retried = sum(1 for i in model_items if i["response"]["meta"]["source"] == "llm" and i["response"]["meta"]["attempts"] == 2)
    fallbacks = sum(1 for i in model_items if i["response"]["meta"]["source"] == "fallback")

    # ---- escalation against the generator's answer key (NOT against the rule the service uses) ----
    predicted = [i["response"]["safety_flag"] for i in items]
    expected = [bool(truth.loc[i["member_code"], "expected_escalation"]) for i in items]
    esc30 = confusion(predicted, expected)
    snaps = all_snapshots()
    if len(snaps) != len(truth):
        sys.exit(f"the database has {len(snaps)} snapshots but the answer key has {len(truth)} members: wrong --truth file?")
    esc_all = confusion([escalation_needed(s) for s in snaps], [bool(truth.loc[s["member_id"], "expected_escalation"]) for s in snaps])
    wrong_all = [s["member_id"] for s in snaps if escalation_needed(s) != bool(truth.loc[s["member_id"], "expected_escalation"])]

    # ---- latency ----
    all_ms = [i["client_ms"] for i in items]
    model_ms = [i["client_ms"] for i in model_items]

    # ---- write the report ----
    md = [f"# Evaluation report ({n} members)", "",
          "## Summary", "", "| Metric | Result |", "|---|---|",
          f"| Valid JSON: final answers | {final_valid}/{n} = {final_valid / n:.0%} |",
          f"| Valid JSON: the model's own output (before retry/fallback) | {calls - bad_json - failed_calls}/{calls} model calls = {(calls - bad_json - failed_calls) / max(1, calls):.0%} |",
          f"| Model answers accepted on the first try | {first_try}/{len(model_items)} (retry needed: {retried}, fallback used: {fallbacks}) |",
          f"| Checker agrees with my labels | {agree}/{n} = {agree / n:.0%} |",
          f"| Escalation accuracy vs answer key, these {n} members | {esc30['accuracy']:.0%} (precision {esc30['precision']:.0%}, recall {esc30['recall']:.0%}) |",
          f"| Escalation accuracy vs answer key, all {len(snaps)} members | {esc_all['accuracy']:.2%} (precision {esc_all['precision']:.1%}, recall {esc_all['recall']:.1%}) |",
          f"| Latency, all {n} answers | average {np.mean(all_ms):,.0f} ms, 95th percentile {percentile95(all_ms):,.0f} ms |",
          f"| Latency, only answers that called the model ({len(model_ms)}) | average {np.mean(model_ms) if model_ms else 0:,.0f} ms, 95th percentile {percentile95(model_ms) if model_ms else 0:,.0f} ms |",
          "", "## Checker versus my labels", "",
          "| | I said all claims true | I said a claim is false |", "|---|---|---|",
          f"| checker passed | {both_ok} | {checker_ok_me_no} |",
          f"| checker rejected | {checker_no_me_ok} | {sum(1 for p, m in rows if not p and not m)} |",
          "", "Note: the service only returns an answer after the same checker accepted it (or it is the fixed fallback or template), "
          "so the checker is expected to pass nearly every final answer. A disagreement therefore means a false or misleading claim "
          "that the checker cannot see.", "",
          f"## Disagreements ({len(disagreements)})", ""]
    if not disagreements:
        md.append("None.")
    for item, passed, problems, mine in disagreements:
        resp = item["response"]
        md += [f"### {item['member_code']}  (checker: {'passed' if passed else 'rejected'}, me: {'true' if mine['label'] else 'false'})", "",
               f"- insight: {resp['insight']}", f"- evidence: {resp['evidence']}", f"- my note: {mine['note'] or '(none)'}",
               f"- checker problems: {problems or 'none'}", ""]
    md += ["## Escalation details", "",
           f"These {n} members: TP {esc30['tp']}, FP {esc30['fp']}, FN {esc30['fn']}, TN {esc30['tn']}.",
           f"All {len(snaps)} members: TP {esc_all['tp']}, FP {esc_all['fp']}, FN {esc_all['fn']}, TN {esc_all['tn']}. "
           f"Members where the service and the answer key differ: {wrong_all or 'none'}.", ""]
    report = "\n".join(md)
    (folder / "EVAL_REPORT.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
