"""Load the CSV files into MySQL with LOAD DATA LOCAL INFILE and print the time taken.

    python scripts/load_data.py --data-dir data/n500  --label n500
    python scripts/load_data.py --data-dir data/n5000 --label n5000

It EMPTIES the data tables first, then loads everything in one transaction (all or nothing).
"""
import argparse
import time
from pathlib import Path

from db import connect

# (table, csv file, columns in CSV order). Parents first, children after.
LOAD_PLAN = [
    ("companies", "companies.csv", "company_id, name, country, created_date"),
    ("members", "members.csv", "member_id, member_code, company_id, age_band, gender, job_type, join_date"),
    ("raw_daily_metrics", "raw_daily_metrics.csv",
     "member_id, metric_date, steps, active_minutes, sleep_hours, resting_hr, wearable_synced"),
    ("engagement", "engagement.csv", "member_id, activity_date, app_opens, content_views, challenge_joined"),
    ("mood_checkins", "mood_checkins.csv", "member_id, checkin_date, mood_score"),
]
# Children first when emptying, because of the foreign keys.
EMPTY_ORDER = ["member_snapshots", "mood_checkins", "engagement", "daily_metrics",
               "raw_daily_metrics", "cleaning_log", "members", "companies"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--label", required=True, help="saved in raw_daily_metrics.load_batch")
    args = parser.parse_args()

    conn = connect(local_infile=True)
    cur = conn.cursor()
    started = time.perf_counter()
    try:
        for table in EMPTY_ORDER:
            cur.execute(f"DELETE FROM `{table}`")
        for table, csv_name, columns in LOAD_PLAN:
            path = (args.data_dir / csv_name).resolve()
            with open(path, "rb") as f:
                expected = sum(1 for _ in f) - 1                     # lines in the file minus the header
            sql = (f"LOAD DATA LOCAL INFILE %s INTO TABLE `{table}` "
                   r"FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"' LINES TERMINATED BY '\n' "
                   f"IGNORE 1 LINES ({columns})")
            if table == "raw_daily_metrics":
                sql += " SET load_batch = %s"
            t0 = time.perf_counter()
            cur.execute(sql, (path.as_posix(), args.label) if table == "raw_daily_metrics" else (path.as_posix(),))
            seconds = time.perf_counter() - t0
            loaded = cur.rowcount
            cur.execute("SHOW WARNINGS")                             # LOCAL turns errors into warnings, so we check
            warnings = cur.fetchall()
            if loaded != expected or warnings:
                raise RuntimeError(f"{table}: file has {expected} rows, loaded {loaded}, warnings: {warnings[:1]}")
            print(f"{table:20}{loaded:>10,} rows{seconds:>8.2f}s")
        conn.commit()                                                # everything becomes visible together
    except Exception:
        conn.rollback()                                              # nothing from this run stays
        raise
    finally:
        conn.close()
    print(f"TOTAL {time.perf_counter() - started:.2f}s")


if __name__ == "__main__":
    main()
