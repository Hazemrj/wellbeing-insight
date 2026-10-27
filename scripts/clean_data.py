"""Run sql/clean_daily_metrics.sql (raw_daily_metrics -> daily_metrics) and print how many values were removed.

    python scripts/clean_data.py
"""
from pathlib import Path

from db import connect

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "clean_daily_metrics.sql"


def main():
    conn = connect(multi_statements=True)
    cur = conn.cursor()
    try:
        cur.execute(SQL_FILE.read_text(encoding="utf-8"))
        while cur.nextset():                                         # surface an error in any later statement
            pass
        conn.commit()                                                # delete + insert + log are saved together
        cur.execute("SELECT column_name, rule_text, values_received, values_removed FROM cleaning_log "
                    "WHERE run_id = (SELECT run_id FROM cleaning_log ORDER BY log_id DESC LIMIT 1) ORDER BY log_id")
        print(f"{'column':16}{'rule':26}{'received':>10}{'removed':>9}")
        for column, rule, received, removed in cur.fetchall():
            print(f"{column:16}{rule:26}{received:>10,}{removed:>9,}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
