# How the benchmark is built

The scripts in `scripts/build/` rebuild the release content from the public source files: the
same records, the same pairs and labels. They do not reproduce the published ids or the
train / dev / test assignment without the private key (see [Reproducing](#reproducing)).

1. `extract_fpds.py OUT.parquet FY*_All_Contracts_Full_*.zip` reads the USAspending "All
   Contracts Full" downloads (FPDS prime transactions) and keeps one row per distinct recipient
   UEI, raw name, doing-business-as name and address, with first and last action dates. FY2025 to
   FY2027 to date read 12,287,036 transactions into 195,849 distinct rows.
2. `build_bench.py` loads every source listed in [format.md](format.md#sources), filters,
   generates pairs, assigns labels, confidence, strata and splits, and masks identifiers.
3. `package_release.py` writes the CSV and Parquet files (also one Parquet file per split),
   draws the 5,000-pair fixture and writes `manifest.json` with SHA-256 sums of the full files.

The identifier mask is an HMAC-SHA256 keyed by `USORG_SALT`, which is not published. Without it
nobody can map an `entity_id` back to a UEI or CIK, so a method cannot shortcut the benchmark by
looking identifiers up. The names, addresses and sources are public records and are published
as printed.

## Filters

* **Organizations only.** Every UEI that FPDS ever flags `sole_proprietorship` is dropped with all
  its records, FCC applicants of type individual are dropped, and any name shaped like a
  person's (two to four words, no organization word, and a given name first or after a comma, or
  a credential such as MD or CPA) is dropped. The given-name list is the first tokens of the
  officer and principal names in the four state registries (tokens seen 60 or more times).
* Names that are placeholders (`REDACTED`, `MULTIPLE RECIPIENTS`, `PARTY INFO NOT FOUND`, ...)
  are dropped. Colorado registry suffixes such as ", Dissolved May 8, 2026" are cut off.
* Fields that do not reliably name the identifier's holder are not used: FPDS and USAspending
  parent-name fields, FCC LMS `licensee_dba`, FCC ownership-report interest holders, and the FRN
  printed on USAC Form 470.
* An identifier seen under more than 8 distinct normalized names is skipped as a shared filer.

## Pairs

**Matches** are pairs of records with the same identifier value whose names differ after case
and punctuation folding. Up to 4 pairs per identifier, cross-source pairs first.

**Non-matches** are pairs with different values of the same identifier type, chosen to be
confusable: same normalized name (legal-form words dropped), or a shared rare name token. State
registry non-matches are two filings in one state whose names reduce to the same key.

Pairs where the identifier label does not answer "same organization?" are dropped:

| dropped | why |
|---|---|
| near-identical names, different identifiers, same state | one organization often holds several UEIs (a registration per site or unit) or CCNs (one per campus) |
| near-identical company names (no government word), different states, same legal form | one company registers per site |
| registry pairs where either filing is converted, merged, withdrawn or pending | the other filing may be its successor |
| FRN matches below similarity 75 or with different legal forms | affiliates share FRNs and FRNs move with license sales |
| DBA pairs across states, and DBAs that are themselves an LLC or corporation name below similarity 70 | the DBA field then names another business |

The FRN and DBA rules came out of a pilot audit of 300 pairs on an earlier build: all 5 pilot
pairs judged mislabelled were FRN matches between affiliated licensees, and the DBA rules cover
3 of the pilot's 7 unclear pairs. `build_stats.json` counts every drop.

## Release filters

`package_release.py` applies a last set of drops found by the 300-pair audit of the final build
(see [datasheet.md](datasheet.md#audit)). Pairs are only removed, never resampled, so the audit
sample stays a random sample of what remains. In v1.0:

| dropped | pairs |
|---|---|
| UEI non-matches whose names differ only by a site word (PARENT, HQ, MAIN) | 3 |
| UEI non-matches with one company name (same canonical name, legal form present) in two states | 178 |
| UEI non-matches with the same canonical name in one state | 37 |
| registry non-matches with the same name, same legal form and same city | 146 |
| FRN, BEN or SPIN matches whose names have different legal forms | 45 |
| FRN matches between sister licensees (names differing in one short market token) | 139 |

The canonical name is the name without legal-form and filler words, with common abbreviations
expanded (CO, CORP, DIST, SCH, ST, ...) and tokens sorted. The same step also cuts Colorado
status suffixes that the build regex missed (32 names).

## Sampling and splits

Pairs are sampled per (label, difficulty) stratum toward a 100,000-pair target. DBA aliases
are capped at 25% and state-registry pairs at 45% of a stratum so one mechanism cannot dominate.
The release has fewer than 100,000 pairs for two reasons, both visible in `build_stats.json`:

| stratum (label, difficulty) | quota | candidates | taken | why short |
|---|---|---|---|---|
| match, easy | 18,000 | 13,177 | 13,177 | not enough candidates |
| match, medium | 16,000 | 5,408 | 5,408 | not enough candidates |
| match, hard | 14,000 | 11,606 | 7,748 | 2,394 too few candidates, 3,858 stopped by the DBA cap or the duplicate check |
| non-match, hard | 20,000 | 60,754 | 12,264 | 7,736 stopped by the DBA and state-registry caps or the duplicate check |
| non-match, medium | 17,000 | 9,448 | 9,448 | not enough candidates |
| non-match, easy | 15,000 | 111,290 | 15,000 | full |

That is 63,045 pairs: 25,361 short of the target because strata ran out of candidates and
11,594 because the caps (and a duplicate check on the same two names) stopped the hard strata.
The release filters then drop 548 more, for 62,497. Relaxing the caps would add hard pairs, but
they would be mostly DBA aliases and state-registry form collisions, the two mechanisms the caps
exist to limit.

Records joined by any pair form connected components; each component goes to `train` (50%),
`dev` (10%) or `test` (40%) by a hash of its id. That keeps every identifier in one split.

## Reproducing

`record_id`, `pair_id` and `entity_id` are HMACs under `USORG_SALT`, and the split of a
component is a hash of its masked `entity_id`, so all four depend on the private key. A rebuild
with another key gives the same records, pairs and labels, but different ids and a different
(equally random) train / dev / test assignment. To compare with published results, use the
released files, whose `split` column is the reference assignment. The key stays private because
it is what keeps `entity_id` from being reversed into a UEI or CIK by brute force over the public
identifier lists.
