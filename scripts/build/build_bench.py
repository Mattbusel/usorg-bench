"""Build USORG-Bench from public US government record files.

Usage:
    USORG_SALT=... python build_bench.py --sources SOURCES_DIR --fpds FPDS_RECORDS.parquet \
        --given-names GIVEN_NAMES.csv --out OUT_DIR

SOURCES_DIR holds the per-source parquet files listed in SOURCES below (USAspending,
FCC ULS and LMS, USAC E-Rate, SEC EDGAR, CMS, state business registries). FPDS_RECORDS is
the output of extract_fpds.py. GIVEN_NAMES is a CSV of (tok, n) used by the person-name
filter. USORG_SALT keys the HMAC that masks identifier values; without it the masked ids
cannot be recomputed, which is the point.

Outputs (OUT_DIR): records.parquet, pairs.parquet, build_stats.json.
Every label comes from a government identifier carried on the source record itself:
two records match when they carry the same value of the same identifier type.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import hmac
import json
import os
import random
import re
import sys

import duckdb
import pandas as pd
from rapidfuzz import fuzz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from usorg_bench.normalize import (  # noqa: E402
    legal_form, looks_like_person, name_key, simple_norm, is_acronym_of, load_given_names,
)

SEED = 20261117
GOV_WORDS = set("""CITY COUNTY TOWN TOWNSHIP VILLAGE BOROUGH STATE COMMONWEALTH DEPARTMENT DEPT DIVISION OFFICE
BOARD AUTHORITY COMMISSION DISTRICT SCHOOL SCHOOLS UNIVERSITY COLLEGE LIBRARY TRIBE TRIBAL NATION PUEBLO PARISH
GOVERNMENT SHERIFF POLICE FIRE HOSPITAL HOSPITALS MEDICAL CENTER""".split())
JUNK = re.compile(r"^(PARTY INFO NOT FOUND|REDACTED|MULTIPLE RECIPIENTS|MISCELLANEOUS|PRIVATE INDIVIDUAL|INDIVIDUAL RECIPIENT|"
                  r"NOT APPLICABLE|UNKNOWN|N/?A|NONE|TEST)\b", re.I)
CO_SUFFIX = re.compile(r",\s*(?:Dissolved|Delinquent|Colorado Authority|Withdrawn|Converted|Merged|Expired|"
                       r"Revoked|Noncompliant|Administratively)\b.*\d{4}\s*$", re.I)


def clean(s):
    if s is None or (isinstance(s, float) and s != s):
        return None
    s = re.sub(r"[ \s]+", " ", str(s)).strip().strip(",;")
    s = CO_SUFFIX.sub("", s).strip()
    if len(s) < 3 or JUNK.match(s):
        return None
    return s


def zip5(z):
    z = re.sub(r"\D", "", str(z or ""))
    return z[:5] if len(z) >= 5 else None


def frn_norm(v):
    d = re.sub(r"\D", "", str(v or ""))
    return d.zfill(10) if d and set(d) != {"0"} and len(d) <= 10 else None


def num_norm(v):
    d = re.sub(r"\D", "", str(v or ""))
    return str(int(d)) if d and set(d) != {"0"} else None


# ------------------------------------------------------------------ records
def load_records(src: str, fpds: str) -> pd.DataFrame:
    con = duckdb.connect()
    P = lambda p: os.path.join(src, p).replace("\\", "/")  # noqa: E731
    rows = []

    def add(df, source, kind, id_type):
        df = df.copy()
        df["source"], df["name_kind"], df["id_type"] = source, kind, id_type
        rows.append(df)

    # FPDS prime contract records (raw names as entered on the award, legal name and DBA)
    q = f"""select recipient_uei id, recipient_name_raw name, recipient_doing_business_as_name dba,
                   recipient_parent_uei puei, recipient_parent_name_raw pname,
                   recipient_address_line_1 address, recipient_city_name city, recipient_state_code state,
                   recipient_zip_4_code zip, recipient_country_code country, organizational_type orgtype,
                   sole_proprietorship sole, first_seen, last_seen
            from '{fpds}'"""
    f = con.sql(q).df()
    f = f[f.country.fillna("USA").isin(["USA", ""])]
    f["sole"] = (f.sole == "t") | (f.orgtype == "SOLE PROPRIETORSHIP")
    f["orgtype"] = f.orgtype.fillna("")
    base = ["id", "puei", "address", "city", "state", "zip", "sole", "orgtype", "first_seen", "last_seen"]
    add(f[base + ["name"]], "fpds_contracts", "legal", "uei")
    d = f[f.dba.fillna("").str.len() > 2][base + ["dba"]].rename(columns={"dba": "name"})
    add(d, "fpds_contracts", "dba", "uei")
    # The parent-name fields are not used: in FPDS they often carry an intermediate owner's or the
    # recipient's own name rather than the name registered under the parent UEI.

    # USAspending recipient profiles (normalized names) and DoD recipients
    for fn, s in (("usaspending/all_recipients_fy25.parquet", "usaspending_recipients"),
                  ("usaspending/dod_recipients_fy24_26.parquet", "usaspending_recipients")):
        r = con.sql(f"""select recipient_uei id, recipient_name name, address, city, state, zip, country,
                        parent_uei puei, parent_name pname from '{P(fn)}'""").df()
        r = r[r.country.fillna("USA").isin(["USA", "UNITED STATES", ""])]
        add(r[["id", "name", "address", "city", "state", "zip", "puei"]], s, "legal", "uei")

    # DoD subawards: the sub-recipient name as the prime reported it
    r = con.sql(f"""select "Sub-Recipient UEI" id, "Sub-Awardee Name" name,
                    "Sub-Recipient Location".address_line1 address, "Sub-Recipient Location".city_name city,
                    "Sub-Recipient Location".state_code state, "Sub-Recipient Location".zip5 zip,
                    "Sub-Recipient Location".location_country_code country
                    from '{P('subawards/dod_subawards_top.parquet')}'""").df()
    r = r[r.country.fillna("USA") == "USA"]
    add(r[["id", "name", "address", "city", "state", "zip"]], "usaspending_subawards", "legal", "uei")

    # FCC ULS licensees (non-individual applicants)
    r = con.sql(f"""select frn id, entity_name name, street_address address, city, state, zip_code zip, applicant_type_code atc
                    from '{P('fcc/uls_licensees.parquet')}' where coalesce(applicant_type_code,'') <> 'I'
                    and coalesce(entity_name,'') <> ''""").df()
    r["id"] = r.id.map(frn_norm)
    add(r[["id", "name", "address", "city", "state", "zip"]], "fcc_uls", "legal", "frn")
    r = con.sql(f"""select licensee_frn id, licensee_name name, licensee_address1 address, licensee_city city,
                    licensee_state state, licensee_zip zip, licensee_dba dba from '{P('fcc/broadcast_facilities.parquet')}'""").df()
    r["id"] = r.id.map(frn_norm)
    add(r[["id", "name", "address", "city", "state", "zip"]], "fcc_lms", "legal", "frn")
    # LMS licensee_dba often names a station or a sister licensee, and ownership-report interest
    # holders are keyed by the respondent's filing: neither is used.

    # USAC E-Rate: billed entities (BEN, and the FRN they file under) and service providers (SPIN)
    r = con.sql(f"""select billed_entity_number ben, billed_entity_name name, ben_fcc_registration_number frn,
                    ben_address_1 address, billed_entity_city city, billed_entity_state state, billed_entity_zip zip
                    from '{P('usac/form470.parquet')}'""").df()
    r["id"] = r.ben.map(num_norm)
    add(r[["id", "name", "address", "city", "state", "zip"]], "usac_form470", "legal", "ben")
    # The Form 470 FRN field is often the school district's or consultant's FRN, so it is not used.
    r = con.sql(f"""select billed_entity_number ben, billed_entity_name n1, billed_entity_name_applicant_invoice n2,
                    billed_entity_state state, inv_service_provider_id_number_spin spin, inv_service_provider_name sp
                    from '{P('usac/invoices.parquet')}'""").df()
    b = pd.concat([r[["ben", "n1", "state"]].rename(columns={"n1": "name"}),
                   r[["ben", "n2", "state"]].rename(columns={"n2": "name"})])
    b["id"] = b.ben.map(num_norm)
    add(b[["id", "name", "state"]], "usac_invoices", "legal", "ben")
    s = r[["spin", "sp"]].rename(columns={"sp": "name"})
    s["id"] = s.spin.map(num_norm)
    add(s[["id", "name"]], "usac_invoices", "legal", "spin")

    # SEC EDGAR: company tickers file and XBRL frames entity names
    r = con.sql(f"select cik id, title name from '{P('sec_frames/tickers.parquet')}'").df()
    add(r, "sec_tickers", "legal", "cik")
    r = con.sql(f"select cik id, entity name, loc from '{P('sec_frames/wide.parquet')}'").df()
    r = r[r["loc"].fillna("").str.startswith("US-")]
    r["state"] = r["loc"].str[3:]
    add(r[["id", "name", "state"]], "sec_xbrl_frames", "legal", "cik")

    # CMS: Hospital General Information and hospital cost reports, keyed by CCN
    r = con.sql(f"""select facility_id id, facility_name name, address, city_town city, state, zip_code zip
                    from '{P('cms/hospitals.parquet')}'""").df()
    add(r, "cms_hospitals", "legal", "ccn")
    for yr in ("2023", "2024"):
        r = con.sql(f"""select provider_ccn id, hospital_name name, street_address address, city, state_code state, zip_code zip
                        from '{P(f'cms/cost_report_{yr}.parquet')}'""").df()
        add(r, "cms_cost_reports", "legal", "ccn")

    df = pd.concat(rows, ignore_index=True)
    for c in ("puei", "address", "city", "state", "zip", "orgtype", "first_seen", "last_seen"):
        if c not in df:
            df[c] = None
    df["sole"] = df["sole"].fillna(False).astype(bool)
    df["id"] = df["id"].astype("string").str.strip().str.upper()
    df.loc[df.id_type.isin(["cik", "ben", "spin"]), "id"] = df.loc[df.id_type.isin(["cik", "ben", "spin"]), "id"].map(num_norm)
    df.loc[df.id_type == "ccn", "id"] = df.loc[df.id_type == "ccn", "id"].str.zfill(6)
    df = df[df.id.notna() & (df.id != "")]
    df = df[(df.id_type != "uei") | (df.id.str.len() == 12)]
    df["name"] = df["name"].map(clean)
    df = df[df.name.notna()]
    for c in ("address", "city"):
        df[c] = df[c].map(lambda v: clean(v) if isinstance(v, str) else None)
    df["state"] = df["state"].map(lambda v: str(v).strip().upper()[:2] if isinstance(v, str) and v.strip() else None)
    df["zip"] = df["zip"].map(zip5)
    return df.reset_index(drop=True)


def load_registry_negatives(src: str) -> pd.DataFrame:
    """State business registry filings (CO, CT, NY, OR) whose names collide on the normalized key.

    A state registry does not accept two filings under the same name, so two filings whose names
    reduce to the same key are different legal entities. Assumed business names (Oregon trade names,
    which can belong to individuals) are skipped.
    """
    con = duckdb.connect()
    P = os.path.join(src, "registry/entities.parquet").replace("\\", "/")
    r = con.sql(f"""select st, rid, name, etype, status, a1 address, city, pstate state, zip from '{P}'
                    where etype not ilike '%ASSUMED%' and name is not null""").df()
    live = {"ACTIVE", "GOOD STANDING", "EXISTS", "DELINQUENT", "NONCOMPLIANT"}
    succ = re.compile(r"CONVERT|MERGE|CONSOLIDAT|DOMESTICAT|WITHDRAW|RENUNCIAT|PENDING", re.I)
    r["status_class"] = r.status.fillna("").map(
        lambda v: "live" if v.upper() in live else ("successor" if succ.search(v) else "ended"))
    r["name"] = r["name"].map(clean)
    r = r[r.name.notna()]
    r["key"] = r.name.map(name_key)
    r = r[r.key.str.len() >= 6]
    dup = r.groupby(["st", "key"]).rid.transform("nunique")
    r = r[(dup >= 2) & (dup <= 6)].copy()
    r["id"] = r.st + ":" + r.rid.astype(str)
    r["id_type"] = "state_filing"
    r["source"] = "state_registry_" + r.st.str.lower()
    r["name_kind"] = "legal"
    r["zip"] = r.zip.map(zip5)
    r["sole"] = False
    return r


# ------------------------------------------------------------------ helpers
def sim(a, b):
    """Token-sort similarity of the names without legal-form words (0-100). Used for strata only."""
    ka, kb = name_key(a) or simple_norm(a), name_key(b) or simple_norm(b)
    return fuzz.token_sort_ratio(ka, kb)


def difficulty(label, s):
    if label:
        return "easy" if s >= 90 else ("medium" if s >= 70 else "hard")
    return "hard" if s >= 90 else ("medium" if s >= 70 else "easy")


def masker(salt: bytes):
    def m(prefix, value, n=14):
        return prefix + hmac.new(salt, str(value).encode(), hashlib.sha256).hexdigest()[:n]
    return m


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True)
    ap.add_argument("--fpds", required=True)
    ap.add_argument("--given-names", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--target-pairs", type=int, default=100_000)
    a = ap.parse_args()
    salt = os.environ.get("USORG_SALT", "").encode()
    if len(salt) < 16:
        sys.exit("set USORG_SALT (16+ chars)")
    mask = masker(salt)
    rng = random.Random(SEED)
    stats = collections.OrderedDict()
    os.makedirs(a.out, exist_ok=True)

    given = load_given_names(a.given_names)
    df = load_records(a.sources, a.fpds)
    stats["records_loaded"] = int(len(df))
    # Organizations only: sole proprietorships (FPDS flag) and person-shaped names are dropped,
    # and every record of an identifier that ever appears as a sole proprietorship goes too.
    sole_ids = set(df.loc[df.sole, "id"])
    stats["dropped_sole_proprietor_flag"] = int(df.id.isin(sole_ids).sum())
    df = df[~df.id.isin(sole_ids)]
    person = df.name.map(lambda n: looks_like_person(n, given))
    stats["dropped_person_like_name"] = int(person.sum())
    df = df[~person]
    df = df[df.orgtype.fillna("") != "SOLE PROPRIETORSHIP"]
    # one record per (source, id, exact name, state); keep the most recent address
    df = df.sort_values("last_seen", na_position="first").drop_duplicates(
        ["source", "id_type", "id", "name", "state"], keep="last")
    stats["records_after_dedupe"] = int(len(df))
    df["norm"] = df.name.map(simple_norm)
    df["key"] = df.name.map(name_key)
    df["form"] = df.name.map(legal_form)
    df = df.astype(object).where(pd.notna(df), None)

    # ---- positives: same identifier, different normalized name strings
    pos = []
    for (t, v), g in df.groupby(["id_type", "id"], sort=False):
        if len(g) < 2 or g.norm.nunique() < 2:
            continue
        recs = g.drop_duplicates("norm").to_dict("records")
        # an identifier seen under many unrelated names is a shared filer/agent: skip it
        if len(recs) > 8:
            continue
        cand = [(x, y) for i, x in enumerate(recs) for y in recs[i + 1:]]
        rng.shuffle(cand)
        cand.sort(key=lambda p: p[0]["source"] == p[1]["source"])  # cross-source first
        for x, y in cand[:4]:
            pos.append((x, y, t, 1))
    stats["positive_candidates"] = len(pos)

    # ---- negatives: different values of the same identifier type, similar names
    neg = []
    lab = df[df.id_type.isin(["uei", "cik", "ccn"])]
    # (a) same normalized key, different identifier
    for (t, k), g in lab.groupby(["id_type", "key"], sort=False):
        if g.id.nunique() < 2 or len(k) < 4:
            continue
        recs = g.drop_duplicates("id").to_dict("records")[:6]
        for i, x in enumerate(recs):
            for y in recs[i + 1:]:
                neg.append((x, y, t, 0))
    # (b) shared rare token, different identifier (medium and easy negatives)
    tokcount = collections.Counter(tok for k in lab.key.unique() for tok in set(k.split()))
    def rare(k):
        toks = [w for w in k.split() if len(w) >= 3]
        return min(toks, key=lambda w: (tokcount[w], w)) if toks else None
    lab = lab.assign(rare=lab.key.map(rare))
    for (t, r_), g in lab[lab.rare.notna()].groupby(["id_type", "rare"], sort=False):
        ids = g.drop_duplicates("id")
        if ids.id.nunique() < 2 or len(ids) > 200:
            continue
        recs = ids.sample(min(len(ids), 6), random_state=rng.randrange(1 << 30)).to_dict("records")
        for i, x in enumerate(recs):
            for y in recs[i + 1:]:
                if x["key"] != y["key"]:
                    neg.append((x, y, t, 0))
    # (c) state registry filings that collide on the normalized key
    reg = load_registry_negatives(a.sources)
    reg["norm"] = reg.name.map(simple_norm)
    reg["key"] = reg.name.map(name_key)
    reg["form"] = reg.name.map(legal_form)
    reg["first_seen"] = reg["last_seen"] = None
    reg["orgtype"] = reg["etype"]
    reg["puei"] = None
    person = reg.name.map(lambda n: looks_like_person(n, given))
    reg = reg[~person]
    reg = reg.astype(object).where(pd.notna(reg), None)
    for (st, k), g in reg.groupby(["st", "key"], sort=False):
        recs = g.drop_duplicates("rid").to_dict("records")
        for i, x in enumerate(recs):
            for y in recs[i + 1:]:
                if x["norm"] != y["norm"]:
                    neg.append((x, y, "state_filing", 0))
    stats["negative_candidates"] = len(neg)

    # ---- pair features, confidence, strata
    def parent_of(r):
        v = r.get("puei")
        return v if isinstance(v, str) and len(v) == 12 else None

    out = []
    for x, y, t, label in pos + neg:
        s = sim(x["name"], y["name"])
        cats = []
        if x["source"] != y["source"]:
            cats.append("cross_source")
        if x["key"] == y["key"]:
            cats.append("same_key")
        if x["form"] and y["form"] and x["form"] != y["form"]:
            cats.append("form_conflict")
        if "dba" in (x["name_kind"], y["name_kind"]):
            cats.append("dba_alias")
        if is_acronym_of(x["name"], y["name"]) or is_acronym_of(y["name"], x["name"]):
            cats.append("acronym")
        if x.get("state") and y.get("state") and x["state"] != y["state"]:
            cats.append("state_differs")
        same_place = bool(x.get("state") and x.get("state") == y.get("state")
                          and ((x.get("city") or "").upper() == (y.get("city") or "").upper() and x.get("city")
                               or (x.get("zip") and x.get("zip") == y.get("zip"))))
        drop = None
        dba = "dba" in (x["name_kind"], y["name_kind"])
        if dba and "state_differs" in cats:
            drop = "dba_other_state"   # the DBA field then names another business, not an alias
        elif dba and s < 70 and legal_form((x if x["name_kind"] == "dba" else y)["name"]):
            drop = "dba_is_another_company"   # a DBA that is itself an LLC or corporation name
        if drop:
            pass
        elif label:
            if t in ("uei", "cik"):
                conf = "high"
            elif t == "frn":
                # One FRN is often shared by affiliated licensees (sister stations, a university and its
                # foundation, a carrier's per-market subsidiaries) and carried over after a license sale,
                # so FRN positives are kept only for close names of the same legal form (pilot audit).
                if s >= 75 and not (x["form"] and y["form"] and x["form"] != y["form"]):
                    conf = "medium"
                else:
                    drop = "frn_positive_not_close"
            elif s >= 60 or same_place:
                conf = "high"
            else:
                conf = "medium"
        else:
            near_same = s >= 95 or x["key"] == y["key"]
            if t == "state_filing":
                stt = {x.get("status_class"), y.get("status_class")}
                if "successor" in stt:
                    drop = "registry_successor"   # converted, merged or withdrawn: may be the other's successor
                else:
                    conf = "high" if stt == {"live"} else "medium"
            elif near_same and x.get("state") == y.get("state"):
                # one organization often holds several identifiers (SAM registrations per site or unit,
                # CMS numbers per campus); with the same name in the same state the identifier label
                # does not say whether the organizations differ
                drop = "near_same_name_same_state"
            elif near_same and not GOV_WORDS.intersection(x["norm"].split() + y["norm"].split()):
                if x["form"] and y["form"] and x["form"] != y["form"]:
                    conf = "medium"   # an LLC and a corporation of one name in two states
                else:
                    drop = "near_same_company_name_other_state"   # likely one company registered per site
            elif t in ("uei", "cik"):
                conf = "high"
            else:
                conf = "medium"
        if drop:
            stats["dropped_pair_" + drop] = stats.get("dropped_pair_" + drop, 0) + 1
            continue
        out.append(dict(left=x, right=y, id_type=t, label=label, name_sim=round(s, 1),
                        difficulty=difficulty(label, s), categories=";".join(cats), label_confidence=conf))
    stats["pairs_candidates"] = len(out)

    # ---- stratified sample to the target size
    by = collections.defaultdict(list)
    for p in out:
        by[(p["label"], p["difficulty"])].append(p)
    for v in by.values():
        rng.shuffle(v)
    share = {(1, "easy"): .18, (1, "medium"): .16, (1, "hard"): .14,
             (0, "hard"): .20, (0, "medium"): .17, (0, "easy"): .15}
    chosen, seen = [], set()
    for k, f in share.items():
        want = int(a.target_pairs * f)
        got = 0
        # caps keep one mechanism from dominating a stratum: DBA aliases (unsolvable from the name
        # alone) at 25%, state-registry form collisions at 45%
        caps = {"dba": int(want * .25), "state_filing": int(want * .45)}
        used = collections.Counter()
        for p in by[k]:
            pk = tuple(sorted((p["left"]["source"] + p["left"]["id"] + p["left"]["name"],
                               p["right"]["source"] + p["right"]["id"] + p["right"]["name"])))
            if pk in seen:
                continue
            kinds = [m for m, hit in (("dba", "dba_alias" in p["categories"]),
                                      ("state_filing", p["id_type"] == "state_filing")) if hit]
            if any(used[m] >= caps[m] for m in kinds):
                continue
            used.update(kinds)
            seen.add(pk)
            chosen.append(p)
            got += 1
            if got >= want:
                break
        stats[f"stratum_{k[0]}_{k[1]}_available"] = len(by[k])
        stats[f"stratum_{k[0]}_{k[1]}_taken"] = got

    # ---- records table and masked ids
    recs = {}
    def rec_id(r):
        rk = "|".join(str(r.get(c) or "") for c in ("source", "id_type", "id", "name", "state", "name_kind"))
        rid = mask("r", rk, 12)
        if rid not in recs:
            recs[rid] = dict(record_id=rid, source=r["source"], name=r["name"], name_kind=r["name_kind"],
                             address=r.get("address") if isinstance(r.get("address"), str) else None,
                             city=r.get("city") if isinstance(r.get("city"), str) else None,
                             state=r.get("state") if isinstance(r.get("state"), str) else None,
                             zip5=r.get("zip") if isinstance(r.get("zip"), str) else None,
                             id_type=r["id_type"], entity_id=mask("e", r["id_type"] + ":" + r["id"], 14))
        return rid

    # entity-disjoint split: union records connected by any chosen pair, split by component
    parent = {}
    def f(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x
    rows = []
    for p in chosen:
        l, r = rec_id(p["left"]), rec_id(p["right"])
        el, er = recs[l]["entity_id"], recs[r]["entity_id"]
        parent[f(el)] = f(er)
        rows.append((l, r, p))
    pairs = []
    for l, r, p in rows:
        comp = f(recs[l]["entity_id"])
        h = int(hashlib.sha256((comp + "split").encode()).hexdigest(), 16) % 100
        split = "train" if h < 50 else ("dev" if h < 60 else "test")
        pid = mask("p", l + r, 12)
        pairs.append(dict(pair_id=pid, left_id=l, right_id=r, label=p["label"], id_type=p["id_type"],
                          label_confidence=p["label_confidence"], difficulty=p["difficulty"],
                          categories=p["categories"], name_sim=p["name_sim"], split=split))
    pairs = pd.DataFrame(pairs).sample(frac=1.0, random_state=SEED).reset_index(drop=True)
    records = pd.DataFrame(list(recs.values())).sort_values("record_id").reset_index(drop=True)
    comp_sizes = collections.Counter(f(e) for e in records.entity_id)
    stats["largest_component_entities"] = max(comp_sizes.values())
    stats["pairs"] = int(len(pairs))
    stats["records"] = int(len(records))
    stats["entities"] = int(records.entity_id.nunique())
    stats["pairs_by_label"] = pairs.label.value_counts().to_dict()
    stats["pairs_by_id_type"] = pairs.id_type.value_counts().to_dict()
    stats["pairs_by_confidence"] = pairs.label_confidence.value_counts().to_dict()
    stats["pairs_by_split"] = pairs.split.value_counts().to_dict()
    stats["records_by_source"] = records.source.value_counts().to_dict()
    records.to_parquet(os.path.join(a.out, "records.parquet"), index=False)
    pairs.to_parquet(os.path.join(a.out, "pairs.parquet"), index=False)
    with open(os.path.join(a.out, "build_stats.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(stats, fh, indent=1, default=str)
    print(json.dumps(stats, indent=1, default=str))


if __name__ == "__main__":
    main()
