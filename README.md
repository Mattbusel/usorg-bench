# usorg-bench

A US organization matching benchmark whose labels come from government identifiers, plus the
loader, metrics, baselines and exports to score entity-resolution tools against it.

Two public records match when they carry the same SAM.gov UEI, SEC CIK, CMS certification
number, FCC registration number, USAC billed-entity or service-provider number, or state
business filing number. Nothing is synthetic and nothing is hand-labelled.

* Dataset: https://huggingface.co/datasets/tensorust/usorg-bench (CC BY 4.0, tag `v1.0.1`)
* 62,497 labelled pairs, 96,642 records, 71,783 distinct identifiers, 15 public sources
* train / dev / test splits disjoint by identifier, difficulty strata, label confidence, 300-pair audit

## Install

```
pip install git+https://github.com/Mattbusel/usorg-bench
pip install "usorg-bench[logicv2,splink] @ git+https://github.com/Mattbusel/usorg-bench"   # baselines
```

## Use

```python
import usorg_bench

data = usorg_bench.load("fixture")   # 5,000 pairs, bundled; "full" downloads the dataset

# a matcher sees only name, address, city, state and zip5
scores = {pid: my_matcher(a, b) for pid, a, b in data.select("dev").iter_feature_pairs()}
scores.update({pid: my_matcher(a, b) for pid, a, b in data.select("test").iter_feature_pairs()})

dev = data.select("dev").pairs
threshold, _ = usorg_bench.best_threshold([p.label for p in dev], [scores[p.pair_id] for p in dev])
print(usorg_bench.evaluate(data.select("test"), scores, threshold))
```

**Leaderboard rule.** A reported result may read only `name`, `address`, `city`, `state` and
`zip5`. `source`, `id_type`, `entity_id`, `name_kind` and the pair columns (`difficulty`,
`categories`, `name_sim`, `label_confidence`, ...) follow from how the pairs were built and
predict the label without reading a name: a lookup on `id_type` and the two sources reaches test
F1 0.927, above every baseline below. `iter_feature_pairs()` hands a matcher only the allowed
fields. Details and measurements: [docs/metrics.md](https://github.com/Mattbusel/usorg-bench/blob/main/docs/metrics.md#allowed-inputs).

```
usorg-bench info --which full
usorg-bench baseline rapidfuzz --which full --out rapidfuzz.csv
usorg-bench eval rapidfuzz.csv --which full          # threshold picked on dev, scored on test (needs dev scores)
usorg-bench export senzing out/ --which full         # or name_bench, zingg
```

## Baselines (test split)

| baseline | fields read | F1 | average precision |
|---|---|---|---|
| Splink (default comparisons, unsupervised) | name, city, state, ZIP | 0.876 | 0.864 |
| nomenklatura LogicV2 | name, address | 0.624 | 0.628 |
| nomenklatura LogicV2 | name | 0.588 | 0.510 |
| RapidFuzz token-sort | name | 0.588 | 0.498 |
| reference: same state, no name | state | 0.800 | 0.680 |

Name-only matchers top out at the all-match F1: the hard strata pair renamed organizations with
different organizations that share a name. Record-level methods should be read against the
same-state reference: the build drops same-state near-name non-matches, so "same state" alone is
worth 0.800. See [docs/baselines.md](https://github.com/Mattbusel/usorg-bench/blob/main/docs/baselines.md).

## Docs

* [docs/format.md](https://github.com/Mattbusel/usorg-bench/blob/main/docs/format.md): columns, sources, submission format
* [docs/datasheet.md](https://github.com/Mattbusel/usorg-bench/blob/main/docs/datasheet.md): composition, labels, audit, limits
* [docs/metrics.md](https://github.com/Mattbusel/usorg-bench/blob/main/docs/metrics.md): metrics and the leaderboard protocol
* [docs/baselines.md](https://github.com/Mattbusel/usorg-bench/blob/main/docs/baselines.md): baseline results and definitions
* [docs/exports.md](https://github.com/Mattbusel/usorg-bench/blob/main/docs/exports.md): nomenklatura name_bench, Senzing truth set, Zingg example
* [docs/build.md](https://github.com/Mattbusel/usorg-bench/blob/main/docs/build.md): how the release is built from public files

Code: MIT. Data: CC BY 4.0. Maintained by Tensorust LLC.
