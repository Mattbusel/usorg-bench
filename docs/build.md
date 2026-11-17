# How the benchmark is built

The scripts in `scripts/build/` rebuild the release from the public source files.

1. `extract_fpds.py OUT.parquet FY*_All_Contracts_Full_*.zip` reads the USAspending "All
   Contracts Full" downloads (FPDS prime transactions) and keeps one row per distinct recipient
   UEI, raw name, doing-business-as name and address, with first and last action dates. FY2025 to
   FY2027 to date read 12,287,036 transactions into 195,849 distinct rows.
2. `build_bench.py` loads every source listed in [format.md](format.md#sources), filters,
   generates pairs, assigns labels, confidence, strata and splits, and masks identifiers.
3. `package_release.py` writes the CSV and Parquet files, draws the 5,000-pair fixture and
   writes `manifest.json` with SHA-256 sums of the full files.

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
Strata with fewer candidates than their quota are taken whole, which is why the release has
fewer than 100,000 pairs.

Records joined by any pair form connected components; each component goes to `train` (50%),
`dev` (10%) or `test` (40%) by a hash of its id. That keeps every identifier in one split.
