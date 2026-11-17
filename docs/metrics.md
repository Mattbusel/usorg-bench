# Metrics and the leaderboard protocol

A submission gives every pair a score from 0 to 1. `usorg-bench eval` reports:

* **precision, recall, F1** at a decision threshold (predicted match when `score >= threshold`),
* **average precision (AP)**, the area under the precision-recall curve as a step sum,
* the same numbers broken down by `difficulty`, `id_type` and `label_confidence`.

The definitions match scikit-learn: AP equals `sklearn.metrics.average_precision_score` and the
threshold metrics equal `precision_recall_fscore_support(average="binary", zero_division=0)`. The
test suite checks both against scikit-learn on random and tied scores.

## Protocol

1. Fit or tune on `train` (and `dev` if you like). Never look at `test` labels.
2. Score `dev` and pick the threshold with the best F1 there.
3. Score `test` and report F1 at that threshold plus AP.

`usorg-bench eval scores.csv` does steps 2 and 3 for you: on the default `--split test` it
picks the best-F1 threshold on the dev pairs in the same scores file. If the file has no dev
scores, pass `--threshold`. A threshold chosen on the test pairs themselves is marked
`oracle_threshold` in the JSON output and is not a leaderboard number.

Splits are entity-disjoint: no organization identifier appears in two splits, so a model cannot
memorize an organization from `train` and meet it again in `test`.

## Name-only and record-level results

Report which fields your method reads. A method that uses only `name` competes with the
name-only baselines; one that also reads address, city, state or ZIP is a record-level method.
Some non-matches are two organizations with the same name in different states (two towns called
Springfield); a name-only method cannot separate them, and that is intended.
