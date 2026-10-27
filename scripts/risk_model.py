"""Risk model: which members stop using the app in the next 14 days? (the only machine-learning step.)

    set ETL_PASSWORD=change_me_etl
    python scripts/risk_model.py

Question: using only what is known on 2026-09-14 (day 76), predict "no app opens at all on days 77-90".
  * The features come from the SQL procedure build_member_features, called for the date 2026-09-14.
  * The label comes from the engagement table, from the days AFTER that date. So the features never see the label.
  * No age, gender, company or job type is used. Only behaviour.

How the decision threshold is chosen without cheating (nested cross-validation):
  outer loop, 5 folds : one fold is held out as the TEST data, the other 4 folds are the training data.
  inner loop, 5 folds : inside the training data only, the model predicts every member out-of-fold. These predictions
                        are the VALIDATION data. The threshold is chosen on them: the highest threshold that still
                        catches at least 80% of the members who really leave (recall >= 0.80).
  Then the model is trained on the whole training part and judged ONCE on the held-out test fold with that threshold.
  The test fold never takes part in choosing the threshold.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score, recall_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect                                          # noqa: E402  (the wb_etl_user connection)

FEATURE_DATE = "2026-09-14"          # day 76: the last day the model may look at
LABEL_END = "2026-09-28"             # day 90: the label looks at days 77 to 90
MIN_RECALL = 0.80                    # product choice: missing a member who leaves costs more than one extra friendly nudge

FEATURES = ["avg_steps_7d", "avg_steps_30d", "steps_change_pct", "avg_active_7d", "avg_active_30d", "active_change_pct",
            "avg_sleep_7d", "sleep_change_pct", "avg_hr_7d", "hr_change_pct",
            "app_opens_7d", "app_opens_30d", "days_since_last_app_open", "app_streak", "active_streak",
            "sync_rate_30d", "mood_low_count"]

LABEL_SQL = f"""
SELECT f.member_id, {', '.join('f.' + c for c in FEATURES)},
       COALESCE(SUM(e.app_opens), 0) = 0 AS leaves                    -- 1 = no app open at all on days 77-90
FROM member_features f
LEFT JOIN engagement e ON e.member_id = f.member_id
                      AND e.activity_date > f.as_of AND e.activity_date <= '{LABEL_END}'
WHERE f.as_of = '{FEATURE_DATE}'
GROUP BY f.member_id, {', '.join('f.' + c for c in FEATURES)}
"""


def load_data() -> pd.DataFrame:
    conn = connect()
    cur = conn.cursor()
    cur.execute("CALL build_member_features(%s)", (FEATURE_DATE,))     # features as they were on day 76
    conn.commit()
    cur.execute(LABEL_SQL)
    columns = [d[0] for d in cur.description]
    df = pd.DataFrame(cur.fetchall(), columns=columns)
    conn.close()
    return df.astype(float)                                            # MySQL DECIMAL arrives as Decimal


def model():
    return make_pipeline(SimpleImputer(strategy="median"),            # a missing value (no synced day) becomes the median
                         StandardScaler(),                             # features on one scale
                         LogisticRegression(max_iter=1000))


def pick_threshold(y_true, prob, min_recall=MIN_RECALL) -> float:
    """The highest threshold whose recall on the validation data is still at least min_recall."""
    best = 0.0
    for t in np.unique(prob):                                          # every possible cut-off
        if recall_score(y_true, prob >= t) >= min_recall:
            best = max(best, float(t))
    return best


def scores(y_true, flagged) -> dict:
    return {"precision": float(precision_score(y_true, flagged, zero_division=0)),
            "recall": float(recall_score(y_true, flagged, zero_division=0)),
            "flagged": int(np.sum(flagged)), "really_leave": int(np.sum(y_true))}


def main():
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    df = load_data()
    X, y = df[FEATURES].to_numpy(), df["leaves"].to_numpy().astype(int)
    print(f"{len(df)} members, {int(y.sum())} leave ({y.mean():.1%})")

    outer = StratifiedKFold(n_splits=5, shuffle=True, random_state=7)
    test_prob = np.zeros(len(y))
    test_flag = np.zeros(len(y), dtype=bool)
    folds = []
    for k, (train, test) in enumerate(outer.split(X, y), start=1):
        inner = StratifiedKFold(n_splits=5, shuffle=True, random_state=k)
        validation_prob = cross_val_predict(model(), X[train], y[train], cv=inner, method="predict_proba")[:, 1]
        threshold = pick_threshold(y[train], validation_prob)          # chosen on validation data only
        fitted = model().fit(X[train], y[train])
        test_prob[test] = fitted.predict_proba(X[test])[:, 1]
        test_flag[test] = test_prob[test] >= threshold                 # applied once to data the threshold never saw
        folds.append({"fold": k, "threshold": round(threshold, 3), **scores(y[test], test_flag[test])})
        print(f"  fold {k}: threshold {threshold:.3f}  test precision {folds[-1]['precision']:.2f}  recall {folds[-1]['recall']:.2f}")

    rule_flag = df["app_opens_7d"].to_numpy() == 0                    # simple baseline: no app open in the last 7 days
    result = {
        "members": len(df), "leave": int(y.sum()), "min_recall_on_validation": MIN_RECALL,
        "model_on_held_out_data": scores(y, test_flag), "roc_auc_held_out": float(roc_auc_score(y, test_prob)),
        "baseline_no_app_open_in_7_days": scores(y, rule_flag), "folds": folds,
        "median_threshold": float(np.median([f["threshold"] for f in folds])),
    }
    out = Path(__file__).resolve().parents[1] / "reports"
    out.mkdir(exist_ok=True)
    (out / "risk_model.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    m, b = result["model_on_held_out_data"], result["baseline_no_app_open_in_7_days"]
    print(f"\nlogistic regression, threshold chosen on validation data, scored on held-out data:"
          f"\n  precision {m['precision']:.2f}  recall {m['recall']:.2f}  (ROC-AUC {result['roc_auc_held_out']:.2f})"
          f"\nbaseline rule 'no app open in 7 days':\n  precision {b['precision']:.2f}  recall {b['recall']:.2f}"
          f"\nsaved {out / 'risk_model.json'}")


if __name__ == "__main__":
    main()
