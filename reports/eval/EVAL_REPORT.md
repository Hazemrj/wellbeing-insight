# Evaluation report (30 members)

## Summary

| Metric | Result |
|---|---|
| Valid JSON: final answers | 30/30 = 100% |
| Valid JSON: the model's own output (before retry/fallback) | 34/34 model calls = 100% |
| Model answers accepted on the first try | 16/25 (retry needed: 8, fallback used: 1) |
| Checker agrees with my labels | 29/30 = 97% |
| Escalation accuracy vs answer key, these 30 members | 100% (precision 100%, recall 100%) |
| Escalation accuracy vs answer key, all 500 members | 100.00% (precision 100.0%, recall 100.0%) |
| Latency, all 30 answers | average 18,843 ms, 95th percentile 34,615 ms |
| Latency, only answers that called the model (25) | average 22,608 ms, 95th percentile 35,034 ms |

## Checker versus my labels

| | I said all claims true | I said a claim is false |
|---|---|---|
| checker passed | 29 | 1 |
| checker rejected | 0 | 0 |

Note: the service only returns an answer after the same checker accepted it (or it is the fixed fallback or template), so the checker is expected to pass nearly every final answer. A disagreement therefore means a false or misleading claim that the checker cannot see.

## Disagreements (1)

### M0459  (checker: passed, me: false)

- insight: Your steps have decreased, but your active minutes have increased, which is a positive change overall.
- evidence: ['steps_7d: 6662.3 vs baseline 7776.4 (-14.3%)', 'active_minutes_7d: 48.3 vs baseline 42.9 (+12.7%)', 'sleep_hours_7d: 6.7 vs baseline 7.6 (-11.8%)']
- my note: calls the week a positive change overall, but steps fell 14.3% and sleep fell 11.8%; the verdict is not supported
- checker problems: none

## Escalation details

These 30 members: TP 5, FP 0, FN 0, TN 25.
All 500 members: TP 14, FP 0, FN 0, TN 486. Members where the service and the answer key differ: none.
