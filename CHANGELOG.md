# Changelog

## 0.1.1 (2026-11-17)

Paired with dataset revision `v1.0.1` on Hugging Face: the same rows as `v1.0`, plus one Parquet
file per split.

- Leaderboard rule: a reported result may read only `name`, `address`, `city`, `state` and
  `zip5`. `source`, `id_type`, `entity_id`, `name_kind` and the pair columns predict the label on
  their own (a lookup on `id_type` and the two sources reaches test F1 0.927); docs/metrics.md
  gives the measurements.
- `BenchmarkData.iter_feature_pairs()` and `features()` return `FeatureRecord`s with only the
  allowed fields. The baselines read records through them (their scores are unchanged).
- `usorg-bench eval` stops with an error when it should pick the threshold on dev but the scores
  file has no dev pairs, or when no `pair_id` in the file belongs to the split. It prints the
  number of scored pairs and warns about unscored and unknown pairs. Scores files with a UTF-8
  byte order mark are accepted.
- `evaluate` adds `by_categories` and `by_identical_name` breakdowns.
- Docs: identical names are always non-matches in v1.0 (format.md); "same state" alone reaches
  F1 0.800 because of the same-state drop rule, so record-level results are read against that
  (baselines.md); the real reasons the release has fewer than 100,000 pairs (build.md); ids and
  splits depend on the private key (build.md); exact export commands (exports.md); 71,783 is a
  count of identifiers, not organizations.
- The Hugging Face card maps `pairs` and `records` to `train`, `validation` and `test`, and the
  broken `fixture_pairs` config now reads Parquet.
- The sdist includes docs/ and scripts/; README links are absolute.

## 0.1.0 (2026-11-17)

First release, paired with the `v1.0` dataset on Hugging Face (`tensorust/usorg-bench`).

- 62,497 labelled pairs over 96,642 public US organization records; labels from UEI, SEC CIK,
  CMS CCN, FCC FRN, USAC BEN and SPIN, and CO/CT/NY/OR state filing numbers.
- Entity-disjoint train/dev/test splits, difficulty strata, label-confidence column,
  300-pair audit.
- `usorg_bench` package: loader (bundled 5,000-pair fixture, checksummed full download),
  scikit-learn compatible metrics, baselines (RapidFuzz, nomenklatura LogicV2, Splink),
  exports (nomenklatura name_bench, Senzing truth set, Zingg example), CLI.
- Build scripts that rebuild the release from the public source files.
