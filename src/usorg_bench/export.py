"""Exports to the formats other entity-resolution tools test against.

* nomenklatura ``contrib/name_bench/cases.csv`` rows (case group ``us_orgs``)
* a Senzing truth set: V4 FEATURES JSONL plus a ``CLUSTER_ID,RECORD_ID,DATA_SOURCE`` key file
* a Zingg example: records CSV, labelled training pairs and a ``config.json``

The Senzing and Zingg exports describe whole clusters, so they only use records whose identifier
type is the same (UEI by default) and drop clusters that could co-refer with another exported
cluster (near-identical names in one state, or one company name across states). The pairwise
benchmark never needs that step because every pair is labelled within one identifier type.
"""
from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Set, TextIO

from .data import BenchmarkData, Pair, Record
from .normalize import canonical_key, legal_form, name_key, simple_norm

NAME_BENCH_FIELDS = ("case_group", "schema", "name1", "name2", "is_match", "quality", "category", "notes")
GOV_WORDS = set("""CITY COUNTY TOWN TOWNSHIP VILLAGE BOROUGH STATE COMMONWEALTH DEPARTMENT DEPT DIVISION OFFICE BOARD
AUTHORITY COMMISSION DISTRICT SCHOOL SCHOOLS UNIVERSITY COLLEGE LIBRARY TRIBE TRIBAL NATION PUEBLO PARISH GOVERNMENT
SHERIFF POLICE FIRE HOSPITAL""".split())


# ------------------------------------------------------------------ nomenklatura name_bench
def _nb_category(p: Pair, a: Record, b: Record) -> str:
    c = set(p.categories)
    same_key = name_key(a.name).replace(" ", "") == name_key(b.name).replace(" ", "")
    if p.label and same_key:
        return "legal-form-change" if "form_conflict" in c else "legal-form-or-punctuation"
    if not p.label and same_key:
        return "legal-form-only"
    if "dba_alias" in c and p.name_sim < 70:
        return "dba-alias"
    if "acronym" in c:
        return "acronym"
    if p.label:
        if p.name_sim < 70:
            return "renamed-or-reworded"
        if same_key and "form_conflict" in c:
            return "legal-form-change"
        if same_key:
            return "legal-form-or-punctuation"
        return "abbreviation-or-reordering"
    if "form_conflict" in c and same_key:
        return "legal-form-only"
    if p.name_sim >= 90:
        return "near-name-different-entity"
    return "shared-token-different-entity"


def _nb_quality(p: Pair, category: str) -> str:
    if category in ("dba-alias", "renamed-or-reworded", "legal-form-only", "legal-form-change", "acronym"):
        return "WEAK"  # the name alone cannot carry the label
    if not p.label and p.name_sim >= 95:
        return "WEAK"  # one-token siblings (fund II vs fund III)
    if p.label_confidence == "high" and p.difficulty == "easy":
        return "STRONG"
    return "MEDIUM"


# rows per category in a 300-row export (scaled for other sizes); shortfalls are filled from the rest
NB_QUOTA = {
    1: {"abbreviation-or-reordering": 40, "legal-form-or-punctuation": 25, "legal-form-change": 15, "acronym": 15,
        "renamed-or-reworded": 35, "dba-alias": 20},
    0: {"near-name-different-entity": 60, "legal-form-only": 35, "shared-token-different-entity": 55},
}


def name_bench_rows(data: BenchmarkData, n: int = 300, seed: int = 20261117) -> List[dict]:
    """Rows for nomenklatura's name_bench ``cases.csv``.

    Pairs whose two names are identical after normalization, or identical up to the legal form
    of the same class, are left out (a name-only harness cannot decide them). Half matches,
    half non-matches, spread over the categories in ``NB_QUOTA``.
    """
    rng = random.Random(seed)
    buckets: Dict[tuple, List[dict]] = defaultdict(list)
    seen: Set[tuple] = set()
    for p, a, b in data.iter_named_pairs():
        if simple_norm(a.name) == simple_norm(b.name) or (
                name_key(a.name) == name_key(b.name) and legal_form(a.name) == legal_form(b.name)):
            continue
        if (not p.label and canonical_key(a.name) == canonical_key(b.name)
                and legal_form(a.name) == legal_form(b.name)):
            continue  # one name in two places (CITY OF LOGAN in Utah and Ohio): not decidable from names
        key = tuple(sorted((a.name, b.name)))
        if key in seen:
            continue
        seen.add(key)
        cat = _nb_category(p, a, b)
        schema = "Company" if (legal_form(a.name) or legal_form(b.name)) else "Organization"
        notes = f"{p.id_type.upper()}; {a.source} vs {b.source}"
        buckets[(p.label, cat)].append(dict(
            case_group="us_orgs", schema=schema, name1=a.name, name2=b.name,
            is_match="true" if p.label else "false", quality=_nb_quality(p, cat), category=cat, notes=notes))
    for k in sorted(buckets):
        buckets[k].sort(key=lambda r: (r["name1"], r["name2"]))
        rng.shuffle(buckets[k])
    out: List[dict] = []
    for label in (1, 0):
        want = n // 2 if label else n - n // 2
        quota = NB_QUOTA[label]
        total = sum(quota.values())
        got: List[dict] = []
        for cat, q in quota.items():
            take = round(q * want / total)
            got += buckets[(label, cat)][:take]
            del buckets[(label, cat)][:take]
        rest = [r for k in sorted(buckets) if k[0] == label for r in buckets[k]]
        got += rest[: max(0, want - len(got))]
        out += got[:want]
    return out


def write_name_bench(rows: Sequence[dict], fh: TextIO) -> None:
    w = csv.DictWriter(fh, fieldnames=NAME_BENCH_FIELDS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)


# ------------------------------------------------------------------ cluster selection
def clean_clusters(data: BenchmarkData, id_type: str = "uei", max_entities: Optional[int] = None,
                   seed: int = 20261117) -> Dict[str, List[Record]]:
    """entity_id -> records, for one identifier type, without clusters that could co-refer."""
    recs = [r for r in data.records.values() if r.id_type == id_type]
    by_ent: Dict[str, List[Record]] = defaultdict(list)
    for r in recs:
        by_ent[r.entity_id].append(r)
    # every normalized name key (and state) each entity uses
    owners: Dict[str, Set[str]] = defaultdict(set)
    states: Dict[str, Set[str]] = defaultdict(set)
    for e, rs in by_ent.items():
        for r in rs:
            owners[name_key(r.name)].add(e)
            if r.state:
                states[e].add(r.state)
    bad: Set[str] = set()
    for k, ents in owners.items():
        if len(ents) < 2:
            continue
        gov = bool(GOV_WORDS.intersection(k.split()))
        ents_l = sorted(ents)
        for i, e1 in enumerate(ents_l):
            for e2 in ents_l[i + 1:]:
                if not gov or states[e1] & states[e2] or not states[e1] or not states[e2]:
                    bad.update((e1, e2))
    keep = {e: sorted(rs, key=lambda r: r.record_id) for e, rs in by_ent.items() if e not in bad}
    if max_entities is not None and len(keep) > max_entities:
        rng = random.Random(seed)
        # half the budget goes to entity pairs that a labelled non-match connects (so a sample
        # keeps hard negatives), the rest to multi-record clusters, then single records
        rid_ent = {r.record_id: r.entity_id for rs in keep.values() for r in rs}
        neg = sorted({tuple(sorted((rid_ent[p.left_id], rid_ent[p.right_id]))) for p in data.pairs
                      if not p.label and p.left_id in rid_ent and p.right_id in rid_ent})
        rng.shuffle(neg)
        take: List[str] = []
        chosen: Set[str] = set()
        for e1, e2 in neg:
            if len(take) + 2 > max_entities // 2:
                break
            for e in (e1, e2):
                if e not in chosen:
                    chosen.add(e)
                    take.append(e)
        multi = sorted(e for e, rs in keep.items() if len(rs) > 1 and e not in chosen)
        single = sorted(e for e, rs in keep.items() if len(rs) == 1 and e not in chosen)
        rng.shuffle(multi)
        rng.shuffle(single)
        for pool in (multi, single):
            room = max_entities - len(take)
            take += pool[:room]
        keep = {e: keep[e] for e in sorted(take)}
    return keep


# ------------------------------------------------------------------ Senzing
def senzing_record(r: Record, data_source_prefix: str = "USORG") -> dict:
    feats: List[dict] = [{"RECORD_TYPE": "ORGANIZATION"}]
    feats.append({"NAME_ORG": r.name} if r.name_kind != "dba" else {"NAME_TYPE": "DBA", "NAME_ORG": r.name})
    addr = {"ADDR_TYPE": "BUSINESS"}
    for k, v in (("ADDR_LINE1", r.address), ("ADDR_CITY", r.city), ("ADDR_STATE", r.state),
                 ("ADDR_POSTAL_CODE", r.zip5)):
        if v:
            addr[k] = v
    if len(addr) > 1:
        addr["ADDR_COUNTRY"] = "US"
        feats.append(addr)
    return {"DATA_SOURCE": f"{data_source_prefix}_{r.source.upper()}", "RECORD_ID": r.record_id,
            "FEATURES": feats}


def write_senzing(clusters: Dict[str, List[Record]], records_fh: TextIO, key_fh: TextIO,
                  data_source_prefix: str = "USORG") -> int:
    """Write V4 JSONL records and the truth-set key. Returns the number of records."""
    w = csv.writer(key_fh, lineterminator="\n")
    w.writerow(["CLUSTER_ID", "RECORD_ID", "DATA_SOURCE"])
    n = 0
    for e in sorted(clusters):
        for r in clusters[e]:
            rec = senzing_record(r, data_source_prefix)
            records_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            w.writerow([e, r.record_id, rec["DATA_SOURCE"]])
            n += 1
    return n


# ------------------------------------------------------------------ Zingg
ZINGG_COLUMNS = ("id", "name", "address", "city", "state", "zip")


def zingg_rows(clusters: Dict[str, List[Record]]) -> List[dict]:
    rows = []
    for e in sorted(clusters):
        for r in clusters[e]:
            rows.append({"id": r.record_id, "name": r.name, "address": r.address or "", "city": r.city or "",
                         "state": r.state or "", "zip": r.zip5 or ""})
    return rows


def zingg_training_rows(data: BenchmarkData, clusters: Dict[str, List[Record]], n_pairs: int = 200,
                        seed: int = 20261117) -> List[dict]:
    """Labelled pairs in Zingg's trainingSamples layout: z_cluster, z_isMatch, then the record columns.

    Both records of a pair share one z_cluster value; z_isMatch is 1 for a match and 0 otherwise.
    Only pairs whose records are both in ``clusters`` are used.
    """
    inside = {r.record_id for rs in clusters.values() for r in rs}
    cand = [p for p in data.pairs if p.left_id in inside and p.right_id in inside]
    rng = random.Random(seed)
    rng.shuffle(cand)
    pos = [p for p in cand if p.label][: n_pairs // 2]
    neg = [p for p in cand if not p.label][: n_pairs - len(pos)]
    rows = []
    for i, p in enumerate(sorted(pos + neg, key=lambda p: p.pair_id)):
        for rid in (p.left_id, p.right_id):
            r = data.records[rid]
            rows.append({"z_cluster": str(i + 1), "z_isMatch": str(p.label), "id": r.record_id, "name": r.name,
                         "address": r.address or "", "city": r.city or "", "state": r.state or "",
                         "zip": r.zip5 or ""})
    return rows


def zingg_config(data_path: str, training_path: Optional[str] = None, model_id: int = 108,
                 output_path: str = "/tmp/zinggOutput") -> dict:
    fields = [{"fieldName": "id", "matchType": "dont_use", "fields": "id", "dataType": "string"},
              {"fieldName": "name", "matchType": "fuzzy", "fields": "name", "dataType": "string"},
              {"fieldName": "address", "matchType": "fuzzy", "fields": "address", "dataType": "string"},
              {"fieldName": "city", "matchType": "fuzzy", "fields": "city", "dataType": "string"},
              {"fieldName": "state", "matchType": "exact", "fields": "state", "dataType": "string"},
              {"fieldName": "zip", "matchType": "fuzzy", "fields": "zip", "dataType": "string"}]
    schema = ", ".join(f"{c} string" for c in ZINGG_COLUMNS)
    cfg = {
        "fieldDefinition": fields,
        "output": [{"name": "output", "format": "csv",
                    "props": {"path": output_path, "delimiter": ",", "header": True}}],
        "data": [{"name": "usOrgs", "format": "csv",
                  "props": {"path": data_path, "delimiter": ",", "header": True}, "schema": schema}],
        "labelDataSampleSize": 0.1,
        "numPartitions": 4,
        "modelId": model_id,
        "zinggDir": "models",
    }
    if training_path:
        cfg["trainingSamples"] = [{"name": "usOrgsTraining", "format": "csv",
                                   "props": {"path": training_path, "delimiter": ",", "header": True},
                                   "schema": "z_cluster string, z_isMatch integer, " + schema}]
    return cfg


def write_csv(rows: Iterable[dict], fields: Sequence[str], fh: TextIO) -> None:
    w = csv.DictWriter(fh, fieldnames=list(fields), lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
