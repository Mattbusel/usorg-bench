"""Load USORG-Bench records and pairs.

The 5,000-pair fixture ships inside the package. The full set is published on Hugging Face as
``tensorust/usorg-bench`` and is fetched over HTTPS on first use, checked against the SHA-256 sums
in the bundled manifest, then cached. Nothing here touches the network unless you ask for
``"full"``.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import urllib.request
from dataclasses import dataclass
from typing import IO, Dict, Iterator, List, Optional, Sequence, Tuple

HF_REPO = "tensorust/usorg-bench"
HF_REVISION = "v1.0.1"  # same rows as v1.0, plus per-split Parquet files
HF_BASE = f"https://huggingface.co/datasets/{HF_REPO}/resolve/{HF_REVISION}"
FULL_FILES = {"records": "data/records.csv", "pairs": "data/pairs.csv"}

RECORD_FIELDS = ("record_id", "source", "name", "name_kind", "address", "city", "state", "zip5",
                 "id_type", "entity_id")
PAIR_FIELDS = ("pair_id", "left_id", "right_id", "label", "id_type", "label_confidence", "difficulty",
               "categories", "name_sim", "split")
SPLITS = ("train", "dev", "test")
DIFFICULTIES = ("easy", "medium", "hard")
CONFIDENCES = ("high", "medium", "low")
_OPTIONAL = ("address", "city", "state", "zip5")

# What a matcher may read for a leaderboard result. Everything else (source, id_type, entity_id,
# name_kind and every pair column except the ids) describes how the benchmark was built and
# predicts the label without reading the names; see docs/metrics.md.
FEATURE_FIELDS = ("record_id", "name", "address", "city", "state", "zip5")


@dataclass(frozen=True)
class Record:
    record_id: str
    source: str
    name: str
    name_kind: str
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip5: Optional[str]
    id_type: str
    entity_id: str


@dataclass(frozen=True)
class FeatureRecord:
    """The fields of a record a leaderboard matcher may use (``record_id`` is an opaque key)."""
    record_id: str
    name: str
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip5: Optional[str]


@dataclass(frozen=True)
class Pair:
    pair_id: str
    left_id: str
    right_id: str
    label: int
    id_type: str
    label_confidence: str
    difficulty: str
    categories: Tuple[str, ...]
    name_sim: float
    split: str


class BenchmarkData:
    """Records keyed by ``record_id`` plus the labelled pairs that reference them."""

    def __init__(self, records: Dict[str, Record], pairs: List[Pair]):
        self.records = records
        self.pairs = pairs

    def __len__(self) -> int:
        return len(self.pairs)

    def __iter__(self) -> Iterator[Pair]:
        return iter(self.pairs)

    def select(self, split: Optional[str] = None, *, confidence: Optional[Sequence[str]] = None,
               id_types: Optional[Sequence[str]] = None,
               difficulty: Optional[Sequence[str]] = None) -> "BenchmarkData":
        """A view restricted to one split and/or confidence tiers, identifier types, difficulties."""
        if split is not None and split not in SPLITS:
            raise ValueError(f"unknown split {split!r}; expected one of {SPLITS}")
        ps = [p for p in self.pairs
              if (split is None or p.split == split)
              and (confidence is None or p.label_confidence in confidence)
              and (id_types is None or p.id_type in id_types)
              and (difficulty is None or p.difficulty in difficulty)]
        return BenchmarkData(self.records, ps)

    def pair_records(self, pair: Pair) -> Tuple[Record, Record]:
        return self.records[pair.left_id], self.records[pair.right_id]

    def iter_named_pairs(self) -> Iterator[Tuple[Pair, Record, Record]]:
        """Yield ``(pair, left_record, right_record)`` with every column, labels included.

        For scoring use :meth:`iter_feature_pairs`, which hides the columns that give the label away.
        """
        for p in self.pairs:
            left, right = self.pair_records(p)
            yield p, left, right

    def features(self, record_id: str) -> FeatureRecord:
        """The leaderboard-allowed view of one record (see ``FEATURE_FIELDS``)."""
        r = self.records[record_id]
        return FeatureRecord(r.record_id, r.name, r.address, r.city, r.state, r.zip5)

    def iter_feature_pairs(self) -> Iterator[Tuple[str, FeatureRecord, FeatureRecord]]:
        """Yield ``(pair_id, left, right)`` with only the fields a leaderboard matcher may read."""
        for p in self.pairs:
            yield p.pair_id, self.features(p.left_id), self.features(p.right_id)


def _none(v: Optional[str]) -> Optional[str]:
    return v if v not in (None, "") else None


def _guard(fn):
    """csv.Error from malformed input surfaces as ValueError, like every other input problem."""
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except csv.Error as e:
            raise ValueError(f"malformed CSV: {e}") from None
    wrapper.__name__, wrapper.__doc__ = fn.__name__, fn.__doc__
    return wrapper


@_guard
def read_records(fh: IO[str]) -> Dict[str, Record]:
    out: Dict[str, Record] = {}
    reader = csv.DictReader(fh)
    missing = set(RECORD_FIELDS) - set(reader.fieldnames or ())
    if missing:
        raise ValueError(f"records file is missing columns: {sorted(missing)}")
    for row in reader:
        vals = {k: (_none(row[k]) if k in _OPTIONAL else (row[k] or "")) for k in RECORD_FIELDS}
        if not vals["record_id"] or not vals["name"]:
            raise ValueError("record without record_id or name")
        if vals["record_id"] in out:
            raise ValueError(f"duplicate record_id {vals['record_id']}")
        out[vals["record_id"]] = Record(**vals)
    return out


@_guard
def read_pairs(fh: IO[str], records: Dict[str, Record]) -> List[Pair]:
    out: List[Pair] = []
    seen = set()
    reader = csv.DictReader(fh)
    missing = set(PAIR_FIELDS) - set(reader.fieldnames or ())
    if missing:
        raise ValueError(f"pairs file is missing columns: {sorted(missing)}")
    for row in reader:
        pid = row["pair_id"]
        if pid in seen:
            raise ValueError(f"duplicate pair_id {pid}")
        seen.add(pid)
        if row["left_id"] not in records or row["right_id"] not in records:
            raise ValueError(f"pair {pid} references an unknown record")
        if row["label"] not in ("0", "1"):
            raise ValueError(f"pair {pid}: label must be 0 or 1")
        if row["split"] not in SPLITS:
            raise ValueError(f"pair {pid}: unknown split {row['split']!r}")
        out.append(Pair(pair_id=pid, left_id=row["left_id"], right_id=row["right_id"], label=int(row["label"]),
                        id_type=row["id_type"], label_confidence=row["label_confidence"],
                        difficulty=row["difficulty"],
                        categories=tuple(c for c in (row["categories"] or "").split(";") if c),
                        name_sim=_float(row["name_sim"], pid), split=row["split"]))
    return out


def _float(v: Optional[str], pid: str) -> float:
    try:
        f = float(v or "")
    except ValueError:
        raise ValueError(f"pair {pid}: name_sim is not a number") from None
    if not math.isfinite(f):
        raise ValueError(f"pair {pid}: name_sim is not finite")
    return f


def load_dir(path: str) -> BenchmarkData:
    """Load ``records.csv`` and ``pairs.csv`` from a directory."""
    with open(os.path.join(path, "records.csv"), encoding="utf-8", newline="") as fh:
        records = read_records(fh)
    with open(os.path.join(path, "pairs.csv"), encoding="utf-8", newline="") as fh:
        pairs = read_pairs(fh, records)
    return BenchmarkData(records, pairs)


def fixture_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixture")


def manifest() -> dict:
    with open(os.path.join(fixture_dir(), "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


def cache_dir() -> str:
    base = os.environ.get("USORG_BENCH_CACHE") or os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "usorg-bench")
    return os.path.join(base, HF_REVISION)


def _fetch(rel: str, dest: str, sha256: Optional[str]) -> None:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(f"{HF_BASE}/{rel}", headers={"User-Agent": "usorg-bench"})
    with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310 (fixed https URL)
        blob = resp.read()
    if sha256 and hashlib.sha256(blob).hexdigest() != sha256:
        raise IOError(f"checksum mismatch for {rel}")
    tmp = dest + ".part"
    with open(tmp, "wb") as fh:
        fh.write(blob)
    os.replace(tmp, dest)


def load(which: str = "fixture") -> BenchmarkData:
    """Load ``"fixture"`` (5,000 pairs, bundled) or ``"full"`` (downloaded once, then cached)."""
    if which == "fixture":
        return load_dir(fixture_dir())
    if which != "full":
        raise ValueError("which must be 'fixture' or 'full'")
    d = cache_dir()
    sums = manifest().get("full_sha256", {})
    for key, rel in FULL_FILES.items():
        dest = os.path.join(d, f"{key}.csv")
        if not os.path.exists(dest):
            _fetch(rel, dest, sums.get(rel))
    return load_dir(d)


@_guard
def read_scores(fh: IO[str]) -> Dict[str, float]:
    """Parse a submission: CSV with ``pair_id`` and ``score`` columns, score within [0, 1].

    Rejects empty or duplicate ids and scores that are not finite numbers within [0, 1].
    """
    reader = csv.DictReader(fh)
    if reader.fieldnames and reader.fieldnames[0].startswith("﻿"):  # Excel and utf-8-sig writers
        reader.fieldnames = [reader.fieldnames[0][1:]] + list(reader.fieldnames[1:])
    if not reader.fieldnames or "pair_id" not in reader.fieldnames or "score" not in reader.fieldnames:
        raise ValueError("scores file needs 'pair_id' and 'score' columns")
    out: Dict[str, float] = {}
    for i, row in enumerate(reader, start=2):
        pid = (row.get("pair_id") or "").strip()
        if not pid:
            raise ValueError(f"line {i}: empty pair_id")
        raw = row.get("score")
        try:
            s = float(raw if raw is not None else "")
        except ValueError:
            raise ValueError(f"line {i}: score is not a number") from None
        if not math.isfinite(s) or not 0.0 <= s <= 1.0:
            raise ValueError(f"line {i}: score must be a finite number within [0, 1]")
        if pid in out:
            raise ValueError(f"line {i}: duplicate pair_id {pid}")
        out[pid] = s
    return out
