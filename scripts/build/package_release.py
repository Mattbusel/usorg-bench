"""Turn a build_bench.py output directory into the published layout.

Usage: python package_release.py BUILD_DIR RELEASE_DIR REPO_DIR
       python package_release.py --split-files RELEASE_DIR   (only rewrite the per-split Parquet files)

RELEASE_DIR receives what goes to Hugging Face (data/records.*, data/pairs.*, the per-split
Parquet files the dataset card maps to train / validation / test, and fixture/).
REPO_DIR/src/usorg_bench/fixture receives the 5,000-pair fixture and manifest.json (with the
SHA-256 of the full CSV files so ``usorg_bench.load("full")`` can verify its download).
"""
import hashlib
import json
import os
import re
import sys

import pandas as pd
from rapidfuzz import fuzz

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
from usorg_bench.normalize import canonical_key, legal_form, name_key, simple_norm  # noqa: E402

RECORD_COLS = ["record_id", "source", "name", "name_kind", "address", "city", "state", "zip5", "id_type", "entity_id"]
PAIR_COLS = ["pair_id", "left_id", "right_id", "label", "id_type", "label_confidence", "difficulty", "categories",
             "name_sim", "split"]
FIXTURE_PAIRS = 5000
SEED = 20261117
REVISION = "v1.0.1"


STATUS_SUFFIX = re.compile(r",\s*(?:Dissolved|Delinquent|Colorado Authority|Withdrawn|Converted|Merged|Expired|"
                           r"Revoked|Noncompliant|Administratively)\b.*\d{4}\s*$", re.I)
SITE_WORDS = {"PARENT", "HQ", "HEADQUARTERS", "MAIN", "CORPORATE", "CORP OFFICE"}


def _sim(a, b):
    ka, kb = name_key(a) or simple_norm(a), name_key(b) or simple_norm(b)
    return fuzz.token_sort_ratio(ka, kb)


def _difficulty(label, s):
    if label:
        return "easy" if s >= 90 else ("medium" if s >= 70 else "hard")
    return "hard" if s >= 90 else ("medium" if s >= 70 else "easy")


def release_filters(rec, pairs, stats):
    """Final label-quality filters found by the 300-pair audit of this build. Pairs are only
    dropped (never resampled), so the audit sample stays a random sample of what remains."""
    rec = rec.copy()
    fixed = rec.name.str.contains(STATUS_SUFFIX)
    rec.loc[fixed, "name"] = rec.loc[fixed, "name"].str.replace(STATUS_SUFFIX, "", regex=True).str.strip()
    stats["release_names_status_suffix_removed"] = int(fixed.sum())
    R = rec.set_index("record_id")
    L, Rr = R.loc[pairs.left_id], R.loc[pairs.right_id]
    ln, rn = L.name.values, Rr.name.values
    ls, rs = L.state.values, Rr.state.values
    lc, rc = L.city.fillna("").str.upper().values, Rr.city.fillna("").str.upper().values
    drop = {}
    sims, keep = [], []
    for i, p in enumerate(pairs.itertuples(index=False)):
        a, b = ln[i], rn[i]
        ka, kb, fa, fb = name_key(a), name_key(b), legal_form(a), legal_form(b)
        s = _sim(a, b)
        why = None
        if not p.label and p.id_type == "uei":
            ta, tb = set(ka.split()), set(kb.split())
            extra = (ta ^ tb)
            if (ta <= tb or tb <= ta) and extra and extra <= SITE_WORDS:
                why = "uei_site_word_only"          # CITY OF MELBOURNE vs CITY OF MELBOURNE PARENT
            elif ((s >= 95 or ka == kb or canonical_key(a) == canonical_key(b)) and ls[i] != rs[i]
                  and (fa or fb) and (fa == fb or not (fa and fb))):
                why = "uei_same_company_name_other_state"   # a company with a campus word (UNIVERSITY, CENTER)
            elif canonical_key(a) == canonical_key(b) and ls[i] == rs[i]:
                why = "uei_same_canonical_name_same_state"  # abbreviation variants of one name in one state
        elif not p.label and p.id_type == "state_filing":
            if ka == kb and fa == fb and lc[i] and lc[i] == rc[i]:
                why = "registry_same_name_same_city"       # likely one owner filing twice
        elif p.label and p.id_type in ("spin", "ben", "frn") and fa and fb and fa != fb:
            why = "account_id_positive_form_conflict"       # affiliates share USAC and FCC account numbers
        elif p.label and p.id_type == "frn":
            ta, tb = ka.split(), kb.split()
            if len(ta) == len(tb) and sum(x != y for x, y in zip(ta, tb)) == 1 and \
                    any(len(x) <= 3 and x != y for x, y in zip(ta, tb)):
                why = "frn_sister_licensees"                 # BIG CITY RADIO-LA vs BIG CITY RADIO-CHI
        if why:
            drop[why] = drop.get(why, 0) + 1
            keep.append(False)
        else:
            keep.append(True)
        sims.append(round(float(s), 1))
    pairs = pairs.copy()
    pairs["name_sim"] = sims
    pairs["difficulty"] = [_difficulty(lab, s) for lab, s in zip(pairs.label, sims)]
    pairs = pairs[keep].reset_index(drop=True)
    for k, v in drop.items():
        stats["release_dropped_" + k] = v
    used = set(pairs.left_id) | set(pairs.right_id)
    rec = rec[rec.record_id.isin(used)].reset_index(drop=True)
    stats["pairs"], stats["records"], stats["entities"] = int(len(pairs)), int(len(rec)), int(rec.entity_id.nunique())
    stats["pairs_by_label"] = pairs.label.astype(str).value_counts().to_dict()
    stats["pairs_by_id_type"] = pairs.id_type.value_counts().to_dict()
    stats["pairs_by_confidence"] = pairs.label_confidence.value_counts().to_dict()
    stats["pairs_by_split"] = pairs.split.value_counts().to_dict()
    stats["pairs_by_difficulty"] = (pairs.label.astype(str) + "_" + pairs.difficulty).value_counts().to_dict()
    stats["records_by_source"] = rec.source.value_counts().to_dict()
    return rec, pairs


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write(df, cols, path_csv, path_parquet=None):
    df = df[cols]
    df.to_csv(path_csv, index=False, lineterminator="\n")
    if path_parquet:
        df.to_parquet(path_parquet, index=False)


HF_SPLITS = {"train": "train", "dev": "validation", "test": "test"}


def write_split_files(rec, pairs, out_dir):
    """data/pairs-{train,dev,test}.parquet and records-{...}.parquet (records of a split are the
    ones its pairs reference; splits are entity-disjoint, so no record is in two splits)."""
    os.makedirs(out_dir, exist_ok=True)
    seen = set()
    for split in HF_SPLITS:
        ps = pairs[pairs.split == split].sort_values("pair_id")
        used = set(ps.left_id) | set(ps.right_id)
        assert not used & seen, "a record appears in two splits"
        seen |= used
        rs = rec[rec.record_id.isin(used)].sort_values("record_id")
        ps[PAIR_COLS].to_parquet(os.path.join(out_dir, f"pairs-{split}.parquet"), index=False)
        rs[RECORD_COLS].to_parquet(os.path.join(out_dir, f"records-{split}.parquet"), index=False)


def split_files_only(release):
    rec = pd.read_parquet(os.path.join(release, "data", "records.parquet"))
    pairs = pd.read_parquet(os.path.join(release, "data", "pairs.parquet"))
    write_split_files(rec, pairs, os.path.join(release, "data"))
    fx_ids = set(pd.read_csv(os.path.join(release, "fixture", "pairs.csv"), usecols=["pair_id"]).pair_id)
    fx = pairs[pairs.pair_id.isin(fx_ids)]
    write_split_files(rec, fx, os.path.join(release, "fixture"))


def fixture_sample(pairs):
    """5,000 pairs stratified by split x label x difficulty, kept entity-disjoint across splits
    because whole pairs are taken from the full set (whose splits already are)."""
    groups = pairs.groupby(["split", "label", "difficulty"]).size()
    share = groups / groups.sum()
    want = (share * FIXTURE_PAIRS).round().astype(int)
    diff = FIXTURE_PAIRS - want.sum()
    want.iloc[want.argmax()] += diff
    parts = []
    for key, n in want.items():
        g = pairs[(pairs.split == key[0]) & (pairs.label == key[1]) & (pairs.difficulty == key[2])]
        parts.append(g.sample(n=min(n, len(g)), random_state=SEED))
    return pd.concat(parts).sort_values("pair_id").reset_index(drop=True)


def main():
    if sys.argv[1] == "--split-files":
        split_files_only(sys.argv[2])
        return
    build, release, repo = sys.argv[1:4]
    rec = pd.read_parquet(os.path.join(build, "records.parquet"))
    pairs = pd.read_parquet(os.path.join(build, "pairs.parquet"))
    stats = json.load(open(os.path.join(build, "build_stats.json"), encoding="utf-8"))
    rec, pairs = release_filters(rec, pairs, stats)
    pairs = pairs.sort_values("pair_id").reset_index(drop=True)
    rec = rec.sort_values("record_id").reset_index(drop=True)
    os.makedirs(os.path.join(release, "data"), exist_ok=True)
    os.makedirs(os.path.join(release, "fixture"), exist_ok=True)
    write(rec, RECORD_COLS, os.path.join(release, "data", "records.csv"), os.path.join(release, "data", "records.parquet"))
    write(pairs, PAIR_COLS, os.path.join(release, "data", "pairs.csv"), os.path.join(release, "data", "pairs.parquet"))
    write_split_files(rec, pairs, os.path.join(release, "data"))

    fx = fixture_sample(pairs)
    used = set(fx.left_id) | set(fx.right_id)
    fxr = rec[rec.record_id.isin(used)]
    fdir = os.path.join(repo, "src", "usorg_bench", "fixture")
    os.makedirs(fdir, exist_ok=True)
    for d in (fdir, os.path.join(release, "fixture")):
        write(fxr, RECORD_COLS, os.path.join(d, "records.csv"))
        write(fx, PAIR_COLS, os.path.join(d, "pairs.csv"))
    write_split_files(rec, fx, os.path.join(release, "fixture"))

    manifest = {
        "dataset": "tensorust/usorg-bench",
        "revision": REVISION,
        "full": {"pairs": int(len(pairs)), "records": int(len(rec)), "entities": int(rec.entity_id.nunique())},
        "fixture": {"pairs": int(len(fx)), "records": int(len(fxr))},
        "full_sha256": {f"data/{n}.csv": sha(os.path.join(release, "data", f"{n}.csv")) for n in ("records", "pairs")},
        "build": {k: v for k, v in stats.items() if not isinstance(v, dict)},
    }
    with open(os.path.join(fdir, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=1)
        fh.write("\n")
    with open(os.path.join(release, "build_stats.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(stats, fh, indent=1)
        fh.write("\n")
    print(json.dumps({k: manifest[k] for k in ("full", "fixture")}, indent=1))


if __name__ == "__main__":
    main()
