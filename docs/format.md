# File format

The benchmark is two tables. Both ship as CSV (UTF-8, LF line endings, header row) and, on
Hugging Face, also as Parquet.

## records

One row per source record: one organization name as one public source printed it.

| column | meaning |
|---|---|
| `record_id` | `r` + 12 hex characters. Stable across releases built from the same inputs. |
| `source` | Where the record comes from (see the table below). |
| `name` | The organization name exactly as the source printed it, whitespace collapsed. |
| `name_kind` | `legal` (the registered or reported name) or `dba` (a doing-business-as name the source lists for that same identifier). |
| `address`, `city`, `state`, `zip5` | Business address fields where the source has them; empty otherwise. `state` is a USPS code, `zip5` five digits. |
| `id_type` | The identifier type behind the label: `uei`, `cik`, `ccn`, `frn`, `ben`, `spin` or `state_filing`. |
| `entity_id` | `e` + 14 hex characters: an HMAC of the identifier type and value under a private key. Two records share an `entity_id` exactly when they carry the same identifier value. The raw identifier is not published. |

## pairs

One row per labelled pair of records.

| column | meaning |
|---|---|
| `pair_id` | `p` + 12 hex characters. |
| `left_id`, `right_id` | `record_id`s. Both records always have the same `id_type`. |
| `label` | `1` when both records carry the same identifier value, `0` when they carry different values of the same identifier type. |
| `id_type` | The identifier type that decides the label. |
| `label_confidence` | `high` or `medium`: how directly the identifier label translates into "same organization". See [datasheet.md](datasheet.md#labels). |
| `difficulty` | `easy`, `medium` or `hard` from the token-sort similarity of the two names without legal-form words: matches are hard below 70 and easy from 90; non-matches are hard from 90 and easy below 70. |
| `categories` | `;`-separated tags: `cross_source`, `same_key` (identical names once legal-form words and punctuation are dropped), `form_conflict` (different legal forms, such as LLC and Inc.), `dba_alias`, `acronym`, `state_differs`. |
| `name_sim` | The similarity used for `difficulty`, 0 to 100. Do not feed it to a model as a feature you report results with. |
| `split` | `train`, `dev` or `test`. Splits are entity-disjoint: every `entity_id` appears in one split only. |

## sources

| `source` | publisher | identifier |
|---|---|---|
| `fpds_contracts` | USAspending.gov contract transactions (FPDS), FY2025 to FY2027 to date: `recipient_name_raw` and `recipient_doing_business_as_name` | UEI |
| `usaspending_recipients` | USAspending.gov recipient profiles (all recipients FY2025, DoD recipients FY2024 to FY2026) | UEI |
| `usaspending_subawards` | USAspending.gov DoD subaward records: the subrecipient name as the prime reported it | UEI |
| `sec_tickers`, `sec_xbrl_frames` | SEC EDGAR company tickers file and XBRL frames entity names | SEC CIK |
| `cms_hospitals`, `cms_cost_reports` | CMS Hospital General Information and Hospital Provider Cost Reports (2023, 2024) | CMS Certification Number |
| `fcc_uls`, `fcc_lms` | FCC Universal Licensing System licensees (non-individual applicants) and LMS broadcast facility licensees | FCC Registration Number |
| `usac_form470`, `usac_invoices` | USAC E-Rate FCC Form 470 billed entities and invoice lines | Billed Entity Number, SPIN |
| `state_registry_co`, `_ct`, `_ny`, `_or` | Colorado, Connecticut, New York and Oregon business entity registries | state filing number |

## submissions

`usorg-bench eval` reads a CSV with `pair_id` and `score` columns. Scores must be finite numbers
from 0 to 1, one row per pair. Pairs without a row count as score 0.
