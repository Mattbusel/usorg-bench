# Changelog

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
