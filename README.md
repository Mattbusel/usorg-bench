# usorg-bench

A US organization matching benchmark whose labels come from government identifiers, plus the
loader, metrics, baselines and exports to score entity-resolution tools against it.

Two public records match when they carry the same SAM.gov UEI, SEC CIK, CMS certification
number, FCC registration number, USAC billed-entity or service-provider number, or state
business filing number. Nothing is synthetic and nothing is hand-labelled.

* Dataset: https://huggingface.co/datasets/tensorust/usorg-bench (CC BY 4.0, tag `v1.0`)
* 62,497 labelled pairs, 96,642 records, 71,783 organizations, 15 public sources
* entity-disjoint train / dev / test splits, difficulty strata, label confidence, 300-pair audit

## Install

```
pip install git+https://github.com/Mattbusel/usorg-bench
pip install "usorg-bench[logicv2,splink] @ git+https://github.com/Mattbusel/usorg-bench"   # baselines
```

## Use

```python
import usorg_bench

data = usorg_bench.load("fixture")   # 5,000 pairs, bundled; "full" downloads the dataset
for pair, a, b in data.select("test").iter_named_pairs():
    print(pair.label, a.name, "|", b.name)

scores = {p.pair_id: my_matcher(*data.pair_records(p)) for p in data.pairs}
print(usorg_bench.evaluate(data.select("test"), scores, threshold=0.5))
```

```
usorg-bench info --which full
usorg-bench baseline rapidfuzz --which full --out rapidfuzz.csv
usorg-bench eval rapidfuzz.csv --which full          # threshold picked on dev, scored on test
usorg-bench export senzing out/ --which full         # or name_bench, zingg
```

## Baselines (test split)

| baseline | fields read | F1 | average precision |
|---|---|---|---|
| Splink (default comparisons, unsupervised) | name, city, state, ZIP | 0.876 | 0.864 |
| nomenklatura LogicV2 | name, address | 0.624 | 0.628 |
| nomenklatura LogicV2 | name | 0.588 | 0.510 |
| RapidFuzz token-sort | name | 0.588 | 0.498 |

Name-only matchers top out at the all-match F1: the hard strata pair renamed organizations with
different organizations that share a name. See [docs/baselines.md](docs/baselines.md).

## Docs

* [docs/format.md](docs/format.md): columns, sources, submission format
* [docs/datasheet.md](docs/datasheet.md): composition, labels, audit, limits
* [docs/metrics.md](docs/metrics.md): metrics and the leaderboard protocol
* [docs/baselines.md](docs/baselines.md): baseline results and definitions
* [docs/exports.md](docs/exports.md): nomenklatura name_bench, Senzing truth set, Zingg example
* [docs/build.md](docs/build.md): how the release is built from public files

Code: MIT. Data: CC BY 4.0. Maintained by Tensorust LLC.
