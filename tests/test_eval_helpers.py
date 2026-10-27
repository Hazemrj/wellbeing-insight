"""The small calculations behind the evaluation scripts. Numbers are worked out by hand in the comments."""
import numpy as np
import pandas as pd
import pytest

import eval_report
import eval_run
import risk_model


def test_confusion_counts_and_rates():
    # predicted: T T F F T      truth: T F F T T     ->  tp=2 (1st,5th)  fp=1 (2nd)  fn=1 (4th)  tn=1 (3rd)
    c = eval_report.confusion([True, True, False, False, True], [True, False, False, True, True])
    assert (c["tp"], c["fp"], c["fn"], c["tn"]) == (2, 1, 1, 1)
    assert c["accuracy"] == pytest.approx(3 / 5) and c["precision"] == pytest.approx(2 / 3) and c["recall"] == pytest.approx(2 / 3)


def test_95th_percentile():
    # 1..100: position 0.95 * 99 = 94.05 -> between the 95th value (95) and the 96th (96) -> 95.05
    assert eval_report.percentile95(list(range(1, 101))) == pytest.approx(95.05)


def test_member_choice_is_repeatable_and_has_the_right_groups():
    truth = pd.DataFrame({
        "member_code": [f"M{i:04d}" for i in range(1, 101)],
        "planted_escalation": [1] * 10 + [0] * 90,
        "planted_near_miss": [0] * 10 + [1] * 10 + [0] * 80,
    })
    a = eval_run.choose_members(truth, seed=1, n_escalation=3, n_near_miss=2, n_ordinary=5)
    b = eval_run.choose_members(truth, seed=1, n_escalation=3, n_near_miss=2, n_ordinary=5)
    assert a == b                                                          # same seed, same members
    groups = [m["group"] for m in a]
    assert (groups.count("escalation"), groups.count("near_miss"), groups.count("ordinary")) == (3, 2, 5)
    planted = {m["member_code"]: m["group"] for m in a}
    assert all(int(code[1:]) <= 10 for code, g in planted.items() if g == "escalation")       # M0001-M0010
    assert all(10 < int(code[1:]) <= 20 for code, g in planted.items() if g == "near_miss")   # M0011-M0020
    assert all(int(code[1:]) > 20 for code, g in planted.items() if g == "ordinary")


def test_threshold_is_the_highest_one_that_keeps_the_recall():
    # 5 members who leave (1) have probabilities .9 .8 .7 .6 .2 ; 5 who stay (0) have .5 .4 .3 .2 .1
    y = np.array([1, 1, 1, 1, 1, 0, 0, 0, 0, 0])
    p = np.array([.9, .8, .7, .6, .2, .5, .4, .3, .2, .1])
    # recall at threshold .6 = 4 of 5 = 0.8 (enough), at .7 = 3 of 5 = 0.6 (too low) -> the answer is .6
    assert risk_model.pick_threshold(y, p, min_recall=0.80) == pytest.approx(0.6)
    # with recall 1.0 required, every leaver must be caught, so the threshold falls to .2
    assert risk_model.pick_threshold(y, p, min_recall=1.0) == pytest.approx(0.2)


def test_scores():
    s = risk_model.scores(np.array([1, 1, 0, 0]), np.array([True, False, True, False]))
    assert s["precision"] == 0.5 and s["recall"] == 0.5 and s["flagged"] == 2 and s["really_leave"] == 2
