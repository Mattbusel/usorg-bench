# Exports for other entity-resolution tools

`usorg-bench export FORMAT OUT_DIR` writes the benchmark in a format another tool already tests
against. The released exports are on Hugging Face under `exports/`. Each one is reproduced byte
for byte by:

```
usorg-bench export name_bench exports/name_bench --which full --split test                  # 300 rows (--n default)
usorg-bench export senzing exports/senzing --which full --split test --max-entities 300     # 479 records, 300 clusters
usorg-bench export zingg exports/zingg --which full --split test --max-entities 600         # 974 records, 200 training pairs
usorg-bench export senzing exports/senzing_full --which full                                # 54,781 records, 40,967 clusters
```

## nomenklatura name_bench (`name_bench`)

`us_orgs_cases.csv` has the columns of nomenklatura's `contrib/name_bench/cases.csv` (schema v1):
`case_group` is `us_orgs`, `schema` is `Company` when either name carries a legal form and
`Organization` otherwise, `notes` names the identifier and the two source datasets.

The 300 rows are half matches and half non-matches, spread over nine categories. Pairs whose
names are identical up to case, punctuation, word order, common abbreviations or a legal form of
the same class are left out, because a name-only comparator cannot decide them (they are still
in the main benchmark, where address fields can). `quality` follows the harness rules: `WEAK`
for pairs the name alone cannot carry (DBA aliases, renames, acronyms, pairs differing only in
legal form, one-token siblings such as fund II and fund III), `STRONG` for high-confidence easy
pairs, `MEDIUM` otherwise.

Run through nomenklatura's own harness (`python contrib/name_bench/run.py -c logicv2`,
nomenklatura 4.18.0, threshold 0.7), the 300 `us_orgs` rows score:

| comparator | TP | FP | TN | FN | precision | recall | F1 |
|---|---|---|---|---|---|---|---|
| logicv2 | 73 | 78 | 72 | 77 | 0.483 | 0.487 | 0.485 |
| levenshtein | 35 | 58 | 92 | 115 | 0.376 | 0.233 | 0.288 |

LogicV2 gets all 15 legal-form-change matches (LLC vs Inc. of one name) and 49 of 55
shared-token non-matches. It misses most renames (2 of 35) and every DBA alias and acronym, and
accepts 34 of 35 legal-form-only non-matches. 4 of 65 STRONG rows fail, all matches where one
side drops a legal form or abbreviates a word: `MILPOWER, INC.` vs `MILPOWER` (0.641),
`BINSWANGER ENTERPRISES LLC` vs `BINSWANGER ENTERPRISES` (0.699), `CHELSEA SCHOOL DISTRICT` vs
`CHELSEA SCHOOL DIST` (0.630), and a name truncated at 30 characters by FPDS,
`RESEARCH AND DEVELOPMENT SOLUT` vs `RESEARCH & DEVELOPMENT SOLUTIONS INC` (0.413).

## Senzing truth set (`senzing`)

* `usorgs.jsonl`: one Senzing V4 record per line: `DATA_SOURCE` (`USORG_<SOURCE>`), `RECORD_ID`,
  `FEATURES` with `RECORD_TYPE: ORGANIZATION`, `NAME_ORG` (a DBA gets `NAME_TYPE: DBA`) and a
  `BUSINESS` address with `ADDR_COUNTRY: US`.
* `usorgs_truthset_key.csv`: `CLUSTER_ID,RECORD_ID,DATA_SOURCE`, the same layout as the
  alternate key that `sz_audit -p` reads in Senzing's truth-sets demo.

A truth set claims that records in different clusters are different entities, which pairwise
labels do not need. The export therefore keeps one identifier type (UEI by default) and drops any
cluster that shares a normalized name with another cluster, unless both are government names in
different states. With `--max-entities`, half of the entity budget goes to pairs of entities that a labelled non-match connects, so a sample keeps its hard negatives. The released set (`--split test --max-entities 300`) has 479 records in 300 clusters, under the 500-record limit of Senzing's evaluation license; `exports/senzing_full`
applies the same rule to the whole benchmark (54,781 records in 40,967 clusters).

Checked with Senzing SDK 4.4.4 (`senzing/senzingsdk-tools:4.4.4`, SQLite repository, default
configuration plus the two data sources) using `scripts/check_senzing.sh`: all 479 records load,
and `sz_audit` of the `sz_snapshot` output against `usorgs_truthset_key.csv` reports 367 Senzing
entities for 300 true clusters, pairwise precision 0.9916, recall 0.590 and F1 0.740 (118 of 200
true pairs found, 1 extra pair).

## Zingg example (`zingg`)

* `usOrgs.csv`: `id,name,address,city,state,zip` with a header.
* `training.csv`: labelled pairs in Zingg's `trainingSamples` layout (`z_cluster`, `z_isMatch`,
  then the record columns; both rows of a pair share `z_cluster`).
* `config.json`: field definitions (`id` not used, `state` exact, the rest fuzzy), the data and
  training sources under `examples/us-orgs/`, model id 108.

Same cluster rule as the Senzing export. The released example (`--split test --max-entities 600`)
has 974 records, and its `training.csv` holds 100 matches and 100 non-matches (Zingg refuses to
train on one class). Smaller `--max-entities` values give fewer training pairs.

Checked with Zingg 0.7.0 on Spark 3.5.5 (`local[4]`, driver memory 4 GB): `--phase train` and
`--phase match` both complete on the released example. Scored against the true grouping over
record pairs, the match output had precision 0.366, recall 0.908 and F1 0.521 (1,050 predicted
pairs, 423 true pairs, 974 records). The training pairs come from the same records, so this is an
in-sample check that the example runs, not a benchmark result.
