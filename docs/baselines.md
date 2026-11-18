# Baselines

Measured on the v1.0 test split (25,175 pairs, 10,475 matches) with
`python scripts/run_baselines.py DATA_DIR OUT_DIR` (Python 3.12, rapidfuzz 3.14.6,
nomenklatura 4.18.0, splink 5.0.0). Each baseline scores dev and test; the threshold is the best
F1 on dev, applied to test. Every baseline reads records through
`BenchmarkData.iter_feature_pairs()`, so it sees only the allowed fields of
[metrics.md](metrics.md#allowed-inputs). Scores per pair (rounded to 6 decimals, which is what the numbers below are computed from) are on Hugging Face under `baselines/`.

| baseline | fields read | test F1 | precision | recall | average precision | dev threshold |
|---|---|---|---|---|---|---|
| splink | name + city, state, ZIP | 0.876 | 0.861 | 0.891 | 0.864 | 0.0024 |
| logicv2_full | name + address | 0.624 | 0.561 | 0.703 | 0.628 | 0.6989 |
| logicv2 | name | 0.588 | 0.416 | 1.000 | 0.510 | 0.0000 |
| rapidfuzz | name | 0.588 | 0.416 | 1.000 | 0.498 | 0.0000 |
| reference: state equal | state | 0.800 | 0.696 | 0.941 | 0.680 | 0.6966 |

The last row is not a matcher. It scores each pair by the `train` match rate of "both records
have the same state" and shows how much of the record-level numbers comes from the sampling
design (see below).

Average precision within each difficulty stratum:

| baseline | easy | medium | hard |
|---|---|---|---|
| splink | 0.963 | 0.842 | 0.748 |
| logicv2_full | 0.992 | 0.758 | 0.249 |
| logicv2 | 0.984 | 0.598 | 0.244 |
| rapidfuzz | 0.995 | 0.552 | 0.227 |

## Reading the table

* **Name similarity alone is not enough here, by construction.** The strata put renamed or
  reworded organizations (low name similarity, same identifier) next to different organizations
  with near-identical names (high similarity, different identifiers). Within the easy stratum both
  name-only baselines rank almost perfectly; pooled over all strata the best dev threshold for
  either one is 0, which accepts every pair, so their F1 is the all-match F1 (precision equals
  the 41.6% match rate).
* **Most of what location adds comes from how non-matches were sampled.** The build drops
  non-matches with near-identical names in the same state (one organization often holds a UEI
  per site, so those pairs may be one organization), which leaves 22,325 of the 36,348
  non-matches tagged `state_differs` against 617 of the 26,149 matches. Same state alone, with
  no name at all, gives test F1 0.800. Splink, which adds exact city, state and ZIP comparisons
  to the name, reaches 0.876: the name and the finer location fields add 0.076 over that
  reference. Read record-level results against 0.800, not against the name-only 0.588.
* **CIK pairs.** Splink finds no CIK match at its global threshold (F1 0.0 on the 643 CIK test
  pairs) although it ranks them reasonably (CIK average precision
  0.772): SEC ticker records carry no address, so CIK pairs never collect the location evidence
  that lifts other pairs over the threshold.
* **LogicV2 with an address** improves the medium stratum but not the hard one: hard matches are
  mostly renames, where the address agrees but the names share nothing.

## Baseline definitions

* `rapidfuzz`: `fuzz.token_sort_ratio` of the normalized names (upper case, ASCII, punctuation
  removed), divided by 100.
* `logicv2`: `LogicV2.compare` from nomenklatura on two FtM entities with only `name` set
  (schema `Company` when either name has a legal form, else `Organization`), the same way
  nomenklatura's `contrib/name_bench` harness builds them.
* `logicv2_full`: the same, plus `country=us` and an `address` string (street, city, state, ZIP).
* `splink`: `dedupe_only` model on the records referenced by the scored pairs, comparisons
  `NameComparison("name")`, `ExactMatch` on city, state and ZIP; prior from `block_on("name")`
  with recall 0.7, u by random sampling (2 million pairs), m by EM blocked on state and on the
  first four letters of the name. No labels are used. The benchmark pairs are scored through
  `register_blocked_pairs_for_predict`.

Run time for dev plus test (31,298 pairs) on one machine: rapidfuzz 3 s, logicv2 25 s,
logicv2_full 15 s, splink 604 s (the machine was memory-constrained during that run; an earlier
unconstrained run of the same model took 122 s).
