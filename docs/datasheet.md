# USORG-Bench datasheet (v1.0)

Following the questions of *Datasheets for Datasets* (Gebru et al.).

## Motivation

Entity-resolution tools are usually scored on person records, product catalogs or synthetic
data. There was no public benchmark of real US organization records whose match labels come
from government identifiers instead of human judgement or generated perturbations. USORG-Bench
fills that gap: every label says whether two public records carry the same official identifier.
It is built and maintained by Tensorust LLC.

## Composition

| | v1.0 |
|---|---|
| labelled pairs | 62,497 (26,149 matches, 36,348 non-matches) |
| records | 96,642 |
| distinct identifiers (entities) | 71,783 |
| splits | train 31,199 / dev 6,123 / test 25,175 pairs, entity-disjoint |
| fixture (bundled with the Python package) | 5,000 pairs, 9,756 records, same stratification |

Pairs per identifier type:

| identifier | matches | non-matches | what it identifies |
|---|---|---|---|
| UEI | 17,608 | 24,320 | a SAM.gov registrant (federal contractors and grantees) |
| state filing number | 0 | 8,854 | a business entity filing in the CO, CT, NY or OR registry |
| CMS CCN | 2,821 | 2,404 | a Medicare-certified hospital (a facility) |
| FCC FRN | 3,870 | 0 | an FCC registrant |
| SEC CIK | 807 | 770 | an SEC filer |
| USAC BEN | 948 | 0 | an E-Rate billed entity (school, district, library) |
| USAC SPIN | 95 | 0 | an E-Rate service provider |

FRN, BEN and SPIN give matches only, and state filing numbers non-matches only, because those
identifiers say "same" reliably but not "different" (or the reverse); see [Labels](#labels).

Records come from 15 public sources (see [format.md](format.md#sources)); the largest are
USAspending recipient profiles (42,356 records) and FPDS contract transactions (18,934).

**Difficulty.** `difficulty` is set by the token-sort similarity of the two names with legal-form
words removed: matches are hard below 70 (7,732 pairs), medium from 70 to 89 (5,323), easy from 90
(13,094); non-matches are hard from 90 (11,914), medium from 70 to 89 (9,434), easy below 70
(15,000). Hard matches are renames, reworded agency names, abbreviations and doing-business-as
names; hard non-matches are different organizations with near-identical names (two towns named
Springfield, an LLC and a corporation of the same name, fund II and fund III).

**Organizations only.** Sole proprietorships and person-shaped names are removed (see
[build.md](build.md#filters)). The filter is conservative: it also drops some companies named
after a person ("ROBERT HALF" without a legal form).

**Masked identifiers.** Raw identifier values are replaced by a keyed HMAC (`entity_id`). Names
and business addresses are published as the sources print them.

## Labels

A pair matches when both records carry the same value of one identifier type and does not match
when they carry different values. `label_confidence` says how directly that answers "same
organization?":

* **high**: matches on UEI or CIK (registry-validated legal-entity identifiers), and on CCN, BEN or
  SPIN when the names are similar (60 or more) or the records share a city or ZIP; non-matches on
  UEI or CIK; registry non-matches where both filings are live.
* **medium**: FRN matches (kept only for close names of one legal form), other CCN, BEN and SPIN
  matches, CCN non-matches (two facilities of one hospital system are different CCNs), and
  registry non-matches where a filing has ended.

Pairs where the identifier label clearly does not answer the question are removed, not labelled
low: see the drop table in [build.md](build.md#pairs).

**Known limits of the labels.**

* CCN non-matches are facility-level: two campuses of one hospital company are a non-match.
* A UEI can move with a business after an acquisition, so some matches pair a company's old and
  new names (Toshiba America Medical Systems and Canon Medical Systems USA). That is intended:
  the identifier says it is one registrant.
* DBA records come from the FPDS `recipient_doing_business_as_name` field. Most are trade names
  of the same registrant; a few name a division or a franchise brand ("QUALITY INN").

## Audit

300 test pairs (50 per label x difficulty stratum) were drawn at random from the build and read
one by one by the build agent (Claude, an AI model; not a human annotator). Verdicts are in
`audit/audit_300.csv` on Hugging Face.

* Before the final release filters: 287 agree, 5 disagree, 8 unsure.
* The 5 disagreements were: two UEIs of one city government ("CITY OF MELBOURNE" and "CITY OF
  MELBOURNE PARENT"), affiliates sharing one SPIN, a foundation filed twice in Colorado, sister
  radio licensees sharing one FRN, and one beauty school company with campus UEIs in two states.
  The release filters remove each of those patterns (503 pairs in total, counted in
  `build_stats.json`), including all 5 audited pairs.
* Of the 293 audited pairs left in the release: 285 agree, 0 disagree, 8 unsure. The unsure
  pairs are 4 CCN campus pairs (facility vs company), 3 UEI non-matches that may be related
  businesses at one address, and 1 SPIN match that may be a rename.

The filters were written after reading these errors, so 0 of 293 is an in-sample number. The
honest error estimate for the method is the pre-filter one: 5 of 300 (1.7%), with 8 more (2.7%)
unclear.

An earlier pilot audit of 300 pairs on a previous build found 5 mislabelled pairs, all FRN
matches between affiliated licensees; the FRN rules in the build come from it.

## Collection

All inputs are public records downloaded by Tensorust between November 5 and November 13, 2026:
USAspending.gov bulk downloads (FPDS contracts FY2025 to FY2027 to date, recipient profiles, DoD
subawards), SEC EDGAR company tickers and XBRL frames, CMS Hospital General Information and
Hospital Provider Cost Reports 2023 and 2024, FCC ULS and LMS, USAC Open Data (Form 470, invoices),
and the Colorado, Connecticut, New York and Oregon business registries. No data was bought,
scraped from behind a login, or generated.

## Uses

* Scoring organization name matchers and record-linkage models (pairwise).
* Cluster-level evaluation through the Senzing truth-set export.
* Regression tests for matcher changes (the 5,000-pair fixture is small enough for CI).

Not suitable for: deciding whether two real organizations are legally related (the labels are
about identifier equality), person matching, or non-US data.

## Distribution and license

Data: CC BY 4.0, https://huggingface.co/datasets/tensorust/usorg-bench (tag `v1.0`).
Code: MIT, https://github.com/Mattbusel/usorg-bench. The underlying US federal records are public
domain; state registry records are public records.

## Maintenance

Tensorust LLC maintains the dataset. Errors can be reported as GitHub issues with the `pair_id`.
A new release gets a new tag; `v1.0` will not change.
