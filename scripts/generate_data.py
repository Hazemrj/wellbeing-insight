"""Generate the synthetic CSV files (synthetic wellbeing data).

    python scripts/generate_data.py --members 500  --out data/n500  --seed 42
    python scripts/generate_data.py --members 5000 --out data/n5000 --seed 43

Design notes:
  * Output is CSV files for LOAD DATA, not row-by-row inserts.
  * The planted patterns are checked: every escalation pattern has at least 3 low check-ins in the last 5,
    and every near-miss pattern has exactly 2. An assert stops the script if any
    pattern ever stops matching its name.
  * Ordinary members can never reach the escalation rule by accident, so the answer key is exactly right.
  * Sizes scale: 500 members -> 14 escalation + 8 near-miss cases, 5000 members -> 140 + 80.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import argparse
import time

import numpy as np
import pandas as pd

START_DATE = date(2026, 7, 1)        # day 1
N_DAYS = 90                          # day 90 = 2026-09-28
AS_OF = START_DATE + timedelta(days=N_DAYS - 1)

LOW_MOOD = 2                         # a check-in of 2 or below counts as "low"
ESCALATION_MIN_LOW = 3               # 3 or more low check-ins ...
ESCALATION_WINDOW_CHECKINS = 5       # ... among the last 5 check-ins ...
ESCALATION_WINDOW_DAYS = 14          # ... that happened in the last 14 days

# Hidden "kinds of people". Each has typical daily habits.
ARCHETYPES = {
    #                 steps  active_min sleep  app/day content/day challenge/day mood
    "achiever":     dict(steps=10500, act=55, sleep=7.3, app=3.5,  content=2.0, chal=0.030, mood=3.9, p=0.25),
    "steady":       dict(steps=7500,  act=35, sleep=7.0, app=1.8,  content=0.8, chal=0.012, mood=3.5, p=0.30),
    "desk_curious": dict(steps=4500,  act=15, sleep=6.8, app=2.5,  content=1.6, chal=0.015, mood=3.3, p=0.20),
    "silent_mover": dict(steps=9500,  act=50, sleep=7.1, app=0.4,  content=0.1, chal=0.002, mood=3.6, p=0.13),
    "dabbler":      dict(steps=6000,  act=22, sleep=6.9, app=0.25, content=0.1, chal=0.002, mood=3.2, p=0.12),
}
COMPANIES = [  # (name, country, created_date). Invented names, clearly synthetic.
    ("Demo Company 01", "AE", date(2023, 1, 15)), ("Demo Company 02", "AE", date(2023, 3, 1)),
    ("Demo Company 03", "SA", date(2023, 6, 20)), ("Demo Company 04", "AE", date(2023, 9, 5)),
    ("Demo Company 05", "SA", date(2024, 1, 10)), ("Demo Company 06", "SA", date(2024, 4, 22)),
    ("Demo Company 07", "AE", date(2024, 8, 30)), ("Demo Company 08", "SA", date(2025, 2, 14)),
]
COMPANY_P = [0.22, 0.18, 0.15, 0.13, 0.11, 0.09, 0.07, 0.05]
AGE_BANDS, AGE_P = ["18-24", "25-34", "35-44", "45-54", "55+"], [0.08, 0.32, 0.30, 0.20, 0.10]
GENDERS, GENDER_P = ["female", "male", "undisclosed"], [0.42, 0.55, 0.03]
JOB_TYPES, JOB_P = ["desk", "field", "shift"], [0.55, 0.25, 0.20]

DISENGAGED_SHARE = 0.15
# Per 500 members: 14 planted escalation, 8 near-miss, 30 outliers. Scaled for other sizes.
PER_500 = {"low_mood": 14, "near_miss": 8, "outliers": 30}

# Planted mood endings. Six values = one OLDER check-in followed by the LAST FIVE check-ins (oldest -> newest).
# Only the last five matter for the rule, the first value is a trap for code that looks at 6.
LOW_MOOD_PATTERNS = [
    [3, 2, 1, 3, 2, 2], [3, 3, 2, 2, 2, 3], [4, 1, 2, 1, 3, 2], [3, 4, 2, 2, 2, 3],
    [3, 3, 1, 2, 2, 4], [2, 3, 1, 1, 2, 2], [4, 4, 2, 2, 3, 1],
]
NEAR_MISS_PATTERNS = [   # exactly two low values among the last five
    [3, 2, 3, 2, 4, 3], [4, 3, 2, 3, 2, 4], [3, 3, 2, 4, 2, 3], [2, 2, 3, 4, 2, 3],
]


def count_low(values) -> int:
    """How many values are 2 or below."""
    return sum(1 for v in values if v <= LOW_MOOD)


def escalation_rule(checkins_newest_last) -> bool:
    """The plain-Python version of the rule, used for self-checks and for the answer key."""
    last_five = list(checkins_newest_last)[-ESCALATION_WINDOW_CHECKINS:]
    return count_low(last_five) >= ESCALATION_MIN_LOW


# Fail loudly at import time if a planted pattern does not do what its name says.
for _p in LOW_MOOD_PATTERNS:
    assert escalation_rule(_p), f"escalation pattern {_p} has fewer than 3 low values in its last 5"
for _p in NEAR_MISS_PATTERNS:
    assert count_low(_p[-5:]) == 2 and not escalation_rule(_p), f"near-miss pattern {_p} must have exactly 2 low in its last 5"


@dataclass
class Dataset:
    """Everything the generator returns, one DataFrame per CSV file."""
    companies: pd.DataFrame
    members: pd.DataFrame
    raw_daily_metrics: pd.DataFrame
    engagement: pd.DataFrame
    mood_checkins: pd.DataFrame
    ground_truth: pd.DataFrame      # the answer key, NEVER loaded into the database


def scaled(key: str, n_members: int) -> int:
    return max(1, round(PER_500[key] * n_members / 500))


def make_members(n: int, rng: np.random.Generator) -> pd.DataFrame:
    names = list(ARCHETYPES)
    join_offsets = rng.integers(30, 720, n)
    return pd.DataFrame({
        "member_id": np.arange(1, n + 1),
        "member_code": [f"M{i:04d}" for i in range(1, n + 1)],
        "company_id": rng.choice(np.arange(1, len(COMPANIES) + 1), n, p=COMPANY_P),
        "age_band": rng.choice(AGE_BANDS, n, p=AGE_P),
        "gender": rng.choice(GENDERS, n, p=GENDER_P),
        "job_type": rng.choice(JOB_TYPES, n, p=JOB_P),
        "join_date": [(START_DATE - timedelta(days=int(d))).isoformat() for d in join_offsets],
        "_archetype": rng.choice(names, n, p=[ARCHETYPES[k]["p"] for k in names]),
    })


def pick_special_groups(members: pd.DataFrame, rng: np.random.Generator, n_low: int, n_near: int) -> pd.DataFrame:
    """Decide who fades out, who is a planted escalation case and who is a near-miss case."""
    n = len(members)
    members["_disengaged"] = False
    members["_low_mood"] = False
    members["_near_miss"] = False
    eligible = members.index[members["_archetype"] != "dabbler"].to_numpy()
    fading = rng.choice(eligible, int(round(DISENGAGED_SHARE * n)), replace=False)
    members.loc[fading, "_disengaged"] = True
    pool = members.index[(~members["_disengaged"]) &
                         (members["_archetype"].isin(["achiever", "steady", "desk_curious"]))].to_numpy()
    chosen = rng.choice(pool, n_low + n_near, replace=False)
    members.loc[chosen[:n_low], "_low_mood"] = True
    members.loc[chosen[n_low:], "_near_miss"] = True
    return members


def neutralise_accidental_escalation(mood: np.ndarray) -> None:
    """Make sure an ordinary member cannot accidentally satisfy the escalation rule (edits `mood` in place)."""
    window_start = len(mood) - ESCALATION_WINDOW_DAYS
    idx = [i for i in range(window_start, len(mood)) if not np.isnan(mood[i])]   # check-ins in the last 14 days
    last_five = idx[-ESCALATION_WINDOW_CHECKINS:]
    low = [i for i in last_five if mood[i] <= LOW_MOOD]
    while len(low) >= ESCALATION_MIN_LOW:
        mood[low.pop()] = 3                                                     # lift the newest low value to 3


def simulate_member(m: pd.Series, rng: np.random.Generator, planted_pattern: list[int] | None):
    """Return (metrics rows, engagement rows, mood rows) for one member, as plain DataFrames."""
    a = ARCHETYPES[m["_archetype"]]
    dates = pd.date_range(START_DATE, periods=N_DAYS, freq="D")
    weekend = dates.dayofweek.to_numpy() >= 5                     # Sat/Sun (UAE weekend)
    day = np.arange(1, N_DAYS + 1)
    job = m["job_type"]

    steps_mean = a["steps"] * rng.lognormal(0, 0.15) * (1.25 if job == "field" else 1.0)
    act_mean = a["act"] * rng.lognormal(0, 0.15) * (1.2 if job == "field" else 1.0)
    sleep_mean = a["sleep"] + rng.normal(0, 0.3)
    hr_base = float(np.clip(rng.normal(66, 6) - 0.0006 * (steps_mean - 7000), 48, 85))
    app_rate = a["app"] * rng.lognormal(0, 0.25)
    content_rate = a["content"] * rng.lognormal(0, 0.25)
    mood_mean = a["mood"] + rng.normal(0, 0.35)

    mult = np.ones(N_DAYS)                                        # 1 = fully engaged ... 0 = gone
    if m["_disengaged"]:
        fade_start = int(rng.integers(10, 56))
        gone_day = fade_start + int(rng.integers(15, 51))
        mult = np.clip(1 - (day - fade_start) / (gone_day - fade_start), 0, 1)

    wk = {"desk": 1.12, "field": 0.65, "shift": 0.90}[job]
    steps = steps_mean * np.where(weekend, wk, 1.0) * rng.lognormal(0, 0.22, N_DAYS) * (0.6 + 0.4 * mult)
    active = act_mean * np.where(weekend, wk, 1.0) * rng.lognormal(0, 0.30, N_DAYS) * (0.6 + 0.4 * mult)

    if job == "shift":
        sleep = np.empty(N_DAYS)
        d = 0
        while d < N_DAYS:
            block = int(rng.integers(4, 9))
            block_mean = rng.choice([7.0, 5.5])
            sleep[d:d + block] = block_mean + rng.normal(0, 1.3, min(block, N_DAYS - d))
            d += block
    else:
        sleep = sleep_mean + np.where(weekend, 0.8 if job == "desk" else 0.5, 0.0) + rng.normal(0, 0.6, N_DAYS)
    sleep = np.clip(sleep, 3.0, 11.0)
    hr = hr_base + 1.5 * np.maximum(0, 7 - sleep) + rng.normal(0, 1.8, N_DAYS)

    miss_rate = float(np.clip(rng.beta(2, 26), 0.02, 0.14)) * (1 + 1.5 * (1 - mult))
    synced = np.ones(N_DAYS, bool)
    for i in np.flatnonzero(rng.random(N_DAYS) < miss_rate * 0.8):
        synced[i] = False
        if rng.random() < 0.25 and i + 1 < N_DAYS:
            synced[i + 1] = False

    metrics = pd.DataFrame({
        "member_id": m["member_id"], "metric_date": dates.date,
        "steps": pd.array(np.round(steps), dtype="Int64"),
        "active_minutes": pd.array(np.round(active), dtype="Int64"),
        "sleep_hours": np.round(sleep, 1),
        "resting_hr": pd.array(np.round(hr), dtype="Int64"),
        "wearable_synced": synced.astype(int),
    })
    metrics.loc[~synced, ["steps", "active_minutes", "sleep_hours", "resting_hr"]] = pd.NA

    opens = rng.poisson(app_rate * mult * np.where(weekend, 0.85, 1.0))
    views = np.where(opens > 0, rng.poisson(content_rate * mult), 0)
    chal = rng.random(N_DAYS) < a["chal"] * mult
    p_checkin = np.minimum(0.5, 0.12 + 0.08 * app_rate) * mult
    checks = rng.random(N_DAYS) < p_checkin
    mood_val = np.clip(np.round(mood_mean - 1.0 * (1 - mult) + rng.normal(0, 0.8, N_DAYS)), 1, 5)
    mood = np.where(checks & (opens > 0), mood_val, np.nan)

    if planted_pattern is not None:                               # planted escalation / near-miss member
        mood[-6:] = planted_pattern                               # last 6 days all have a check-in
        mood[:-6] = np.where(rng.random(N_DAYS - 6) < 0.3, np.clip(np.round(rng.normal(3.4, 0.7, N_DAYS - 6)), 3, 5), np.nan)
        opens[-6:] = np.maximum(opens[-6:], 1)
    else:
        neutralise_accidental_escalation(mood)

    engagement = pd.DataFrame({
        "member_id": m["member_id"], "activity_date": dates.date,
        "app_opens": opens, "content_views": views, "challenge_joined": chal.astype(int),
    })
    mood_rows = pd.DataFrame({"member_id": m["member_id"], "checkin_date": dates.date, "mood_score": mood})
    mood_rows = mood_rows.dropna(subset=["mood_score"]).astype({"mood_score": int})
    return metrics, engagement, mood_rows


def inject_outliers(metrics: pd.DataFrame, rng: np.random.Generator, n_outliers: int) -> pd.DataFrame:
    """Put obviously impossible sensor readings into some synced rows."""
    rows = rng.choice(metrics.index[metrics["wearable_synced"] == 1], n_outliers, replace=False)
    bad = [("steps", 150000), ("steps", 99999), ("sleep_hours", 23.5), ("sleep_hours", 0.0),
           ("resting_hr", 0), ("resting_hr", 220), ("active_minutes", 1500)]
    for i, row in enumerate(rows):
        column, value = bad[i % len(bad)]
        metrics.loc[row, column] = value
    return metrics


def generate(n_members: int = 500, seed: int = 42, n_low: int | None = None, n_near: int | None = None) -> Dataset:
    """Build the complete dataset in memory."""
    rng = np.random.default_rng(seed)
    n_low = scaled("low_mood", n_members) if n_low is None else n_low
    n_near = scaled("near_miss", n_members) if n_near is None else n_near
    members = pick_special_groups(make_members(n_members, rng), rng, n_low, n_near)

    low_counter = near_counter = 0                                # cycle through the patterns so every one is used
    metric_parts, engagement_parts, mood_parts = [], [], []
    for _, m in members.iterrows():
        pattern = None
        if m["_low_mood"]:
            pattern = LOW_MOOD_PATTERNS[low_counter % len(LOW_MOOD_PATTERNS)]
            low_counter += 1
        elif m["_near_miss"]:
            pattern = NEAR_MISS_PATTERNS[near_counter % len(NEAR_MISS_PATTERNS)]
            near_counter += 1
        a, b, c = simulate_member(m, rng, pattern)
        metric_parts.append(a)
        engagement_parts.append(b)
        mood_parts.append(c)

    metrics = inject_outliers(pd.concat(metric_parts, ignore_index=True), rng, scaled("outliers", n_members))
    truth = pd.DataFrame({
        "member_id": members["member_id"], "member_code": members["member_code"],
        "archetype": members["_archetype"], "disengaged": members["_disengaged"].astype(int),
        "planted_escalation": members["_low_mood"].astype(int),
        "planted_near_miss": members["_near_miss"].astype(int),
        "expected_escalation": members["_low_mood"].astype(int),      # exactly the planted ones, see module docstring
    })
    companies = pd.DataFrame(COMPANIES, columns=["name", "country", "created_date"])
    companies.insert(0, "company_id", np.arange(1, len(COMPANIES) + 1))
    return Dataset(
        companies=companies,
        members=members.drop(columns=[c for c in members if c.startswith("_")]),
        raw_daily_metrics=metrics,
        engagement=pd.concat(engagement_parts, ignore_index=True),
        mood_checkins=pd.concat(mood_parts, ignore_index=True),
        ground_truth=truth,
    )


def write_csv(dataset: Dataset, out_dir: Path) -> dict[str, int]:
    """Write one CSV per table. NULL is written as \\N, which LOAD DATA understands."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name in ["companies", "members", "raw_daily_metrics", "engagement", "mood_checkins", "ground_truth"]:
        frame = getattr(dataset, name)
        frame.to_csv(out_dir / f"{name}.csv", index=False, na_rep="\\N", lineterminator="\n")
        counts[name] = len(frame)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--members", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    start = time.perf_counter()
    dataset = generate(args.members, args.seed)
    counts = write_csv(dataset, args.out)
    print(f"generated in {time.perf_counter() - start:.1f}s -> {args.out}")
    for name, rows in counts.items():
        print(f"  {name:20} {rows:>9,} rows")
    truth = dataset.ground_truth
    print(f"  planted escalation: {truth.planted_escalation.sum()}  near-miss: {truth.planted_near_miss.sum()}")


if __name__ == "__main__":
    main()
