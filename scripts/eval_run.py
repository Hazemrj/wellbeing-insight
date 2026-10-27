"""Evaluation step 1 of 3: call the running insight endpoint on 30 members and save what came back.

    python scripts/eval_run.py --truth data/n500/ground_truth.csv

It does NOT run the checker. You label the answers yourself first (see reports/eval/review_sheet.md),
then scripts/eval_report.py compares your labels with the checker.
The endpoint must be running:   uvicorn service.app:app --port 8000     (and APP_DB_PASSWORD must be set)
"""
import argparse
import csv
import json
import random
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))                    # so this script can import the service package

from service import db                           # noqa: E402  (after the path line on purpose)

WORDS = {"steps": "steps", "active_minutes": "active minutes", "sleep_hours": "sleep hours", "resting_hr": "resting heart rate"}


def choose_members(truth: pd.DataFrame, seed: int, n_escalation: int, n_near_miss: int, n_ordinary: int) -> list[dict]:
    """5 planted escalation cases, 5 planted near-misses and 20 ordinary members, picked with a fixed seed, in mixed order."""
    rng = random.Random(seed)
    groups = {
        "escalation": truth[truth.planted_escalation == 1],
        "near_miss": truth[truth.planted_near_miss == 1],
        "ordinary": truth[(truth.planted_escalation == 0) & (truth.planted_near_miss == 0)],
    }
    wanted = {"escalation": n_escalation, "near_miss": n_near_miss, "ordinary": n_ordinary}
    chosen = []
    for name, frame in groups.items():
        codes = sorted(frame.member_code)
        chosen += [{"member_code": c, "group": name} for c in rng.sample(codes, wanted[name])]
    rng.shuffle(chosen)                          # mixed order, so the order gives nothing away while you label
    return chosen


def review_text(item: dict) -> str:
    """One member as readable text: the numbers first, then the answer. This is what you judge."""
    snap, resp = item["snapshot"], item["response"]
    lines = [f"## {item['member_code']}", "", "**Member data (as of " + snap["as_of"] + ")**", "",
             "| metric | last 7 days | last 30 days | change |", "|---|---|---|---|"]
    for w in snap["wearable"]:
        change = "n/a" if w["change_pct"] is None else f"{w['change_pct']:+}%"
        lines.append(f"| {WORDS[w['metric']]} | {w['avg_7d']} | {w['avg_30d']} | {change} |")
    app, mood = snap["app"], snap["mood"]
    lines += ["",
              f"- wearable synced on {snap['sync_rate_30d']} of the last 30 days",
              f"- app opens: {app['opens_7d']} in 7 days, {app['opens_30d']} in 30 days; days since last open: {app['days_since_last_open']}",
              f"- app streak: {app['streak_days']} days; active streak (30+ active minutes): {app['active_streak_days']} days",
              f"- last 5 mood check-ins (newest first, 1 = worst, 5 = best): {mood['last5']}",
              "", "**Answer**", "",
              f"- insight: {resp['insight']}",
              f"- evidence: {resp['evidence']}",
              f"- actions: {resp['actions']}",
              f"- tone: {resp['tone']}   safety_flag: {resp['safety_flag']}", "", "---", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", required=True, help="the ground_truth.csv of the data set that is loaded, e.g. data/n500/ground_truth.csv")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default=str(ROOT / "reports" / "eval"))
    ap.add_argument("--seed", type=int, default=26)
    ap.add_argument("--escalation", type=int, default=5)
    ap.add_argument("--near-miss", type=int, default=5)
    ap.add_argument("--ordinary", type=int, default=20)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    truth = pd.read_csv(args.truth)
    members = choose_members(truth, args.seed, args.escalation, args.near_miss, args.ordinary)
    print(f"calling {args.url} for {len(members)} members ...")

    items = []
    for n, m in enumerate(members, start=1):
        t0 = time.perf_counter()
        r = requests.post(f"{args.url}/insight", json={"member_id": m["member_code"]}, timeout=300)
        client_ms = round((time.perf_counter() - t0) * 1000)          # the time the caller waited, in milliseconds
        r.raise_for_status()                                          # a 404/503 here means the setup is wrong: stop
        items.append({**m, "client_ms": client_ms, "response": r.json(), "snapshot": db.fetch_snapshot(m["member_code"])})
        print(f"  {n:2d}/{len(members)}  {m['member_code']}  {items[-1]['response']['meta']['source']:<20} {client_ms} ms")

    (out / "responses.json").write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "review_sheet.md").write_text("# Review sheet: is every claim true for that member's data?\n\n" +
                                         "\n".join(review_text(i) for i in items), encoding="utf-8")
    labels = out / "labels.csv"
    if not labels.exists():                                           # never overwrite labels you already wrote
        with labels.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["member_code", "all_claims_true", "note"])
            for i in items:
                w.writerow([i["member_code"], "", ""])
    print(f"\nsaved {out / 'responses.json'}, {out / 'review_sheet.md'} and {labels}")
    print("NEXT: read review_sheet.md and fill in labels.csv (yes / no) BEFORE running eval_report.py")


if __name__ == "__main__":
    main()
