# Metrics and the leaderboard protocol

A submission gives every pair a score from 0 to 1. `usorg-bench eval` reports:

* **precision, recall, F1** at a decision threshold (predicted match when `score >= threshold`),
* **average precision (AP)**, the area under the precision-recall curve as a step sum,
* the same numbers broken down by `difficulty`, `id_type`, `label_confidence`, `categories`
  (a pair counts once under each of its tags) and `identical_name` (`yes` when the two names are
  equal after case and punctuation folding).

The definitions match scikit-learn: AP equals `sklearn.metrics.average_precision_score` and the
threshold metrics equal `precision_recall_fscore_support(average="binary", zero_division=0)`. The
test suite checks both against scikit-learn on random and tied scores.

## Allowed inputs

A leaderboard result may read only these record fields:

| allowed | not allowed |
|---|---|
| `name`, `address`, `city`, `state`, `zip5`, and `record_id` / `pair_id` / `left_id` / `right_id` as opaque keys | `source`, `id_type`, `entity_id`, `name_kind`, and every other pair column: `label`, `id_type`, `label_confidence`, `difficulty`, `categories`, `name_sim`, `split` |

`BenchmarkData.iter_feature_pairs()` yields `(pair_id, left, right)` where `left` and `right`
are `FeatureRecord`s with exactly the allowed fields; `BenchmarkData.features(record_id)` gives
one record. Score through that view. The reference baselines do.

The excluded columns describe how the benchmark was built, and in v1.0 they predict the label
without reading a name. Measured on the v1.0 test split (25,175 pairs) with a lookup table fit on
`train` (label rate per key) and the threshold picked on `dev`:

| key looked up | test F1 | test AP |
|---|---|---|
| `id_type` + the two records' `source` values | 0.927 | 0.908 |
| the same + state equal + names identical | 0.973 | 0.980 |
| `difficulty` + `categories` | 0.923 | 0.976 |
| which of address, city, state, ZIP are present, + `name_kind` | 0.608 | 0.642 |
| which of address, city, state, ZIP are present | 0.608 | 0.486 |
| state equal (allowed fields only) | 0.800 | 0.680 |
| for comparison: Splink baseline | 0.876 | 0.864 |
| for comparison: accept every pair | 0.588 | |

Why the excluded columns leak:

* State filing numbers give only non-matches (8,854 pairs) and FRN, BEN and SPIN only matches.
* Two USAspending recipient profiles are always a non-match (21,032 pairs, 0 matches), because a
  recipient profile is one row per UEI; an FPDS record against a recipient profile is a match
  15,519 times out of 18,424.
* `difficulty` is computed from the label and `name_sim`, so the two together give the label back.
* A pair with a `dba` record is a match 7,412 times out of 7,580: DBA names enter the benchmark
  through the FPDS doing-business-as field, next to the same UEI's legal name.

The last line of the table is a warning about the allowed fields too. The build drops same-state
near-name non-matches (one organization often holds a UEI per site), so most non-matches are in
different states: `state equal` alone reaches F1 0.800. A record-level method gets that much from
the sampling design, not from understanding organizations. Report the name-only and record-level
results separately (below), and compare record-level results against 0.800, not against 0.588.

## Protocol

1. Fit or tune on `train` (and `dev` if you like). Never look at `test` labels.
2. Score `dev` and pick the threshold with the best F1 there.
3. Score `test` and report F1 at that threshold plus AP.

`usorg-bench eval scores.csv` does steps 2 and 3 for you: on the default `--split test` it
picks the best-F1 threshold on the dev pairs in the same scores file. If the file has no dev
scores it stops with an error; include dev scores or pass `--threshold`. The summary prints how
many pairs were scored, and eval warns when some pairs of the split, or some dev pairs, have no
score (they count as 0 unless `--missing error` or `--missing skip`). A file whose `pair_id`s
match none of the split's pairs is an error. A threshold chosen on the scored pairs themselves
(any split other than `test` without `--threshold`) is marked `oracle_threshold` in the JSON
output and is not a leaderboard number. Files with a UTF-8 byte order mark (Excel,
`encoding="utf-8-sig"`) are read as is.

Splits are disjoint by identifier: no `entity_id` appears in two splits. That does not stop name
memorization. One organization can hold several identifiers (a UEI per site, a CCN per campus),
and different organizations share names, so the same name can sit in `train` and in `test`. In
v1.0, 547 test pairs have both normalized names among the `train` records, and a name-to-entity
lookup built from `train` labels 430 of them correctly. Methods that memorize names from `train`
should say so.

## Name-only and record-level results

Report which fields your method reads. A method that uses only `name` competes with the
name-only baselines; one that also reads address, city, state or ZIP is a record-level method.
Some non-matches are two organizations with the same name in different states (two towns called
Springfield); a name-only method cannot separate them, and that is intended. In v1.0 every pair
whose names are identical after case and punctuation folding is a non-match (see
[format.md](format.md#identical-names)), so the `identical_name: yes` breakdown has no matches.
