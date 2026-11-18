"""The leaderboard protocol: what a matcher may read and how `usorg-bench eval` picks thresholds."""
import dataclasses
import json

import pytest

from usorg_bench import FEATURE_FIELDS, FeatureRecord, evaluate, load, read_scores
from usorg_bench.baselines import rapidfuzz_scores
from usorg_bench.cli import main
from usorg_bench.data import BenchmarkData
from usorg_bench.normalize import simple_norm

LEAKY_RECORD_FIELDS = {"source", "id_type", "entity_id", "name_kind"}


@pytest.fixture(scope="module")
def fx():
    return load("fixture")


def test_feature_view_hides_build_columns(fx):
    names = {f.name for f in dataclasses.fields(FeatureRecord)}
    assert names == set(FEATURE_FIELDS)
    assert not names & LEAKY_RECORD_FIELDS
    got = list(fx.select("test").iter_feature_pairs())
    assert len(got) == len(fx.select("test").pairs)
    for pid, a, b in got[:50]:
        assert isinstance(pid, str) and isinstance(a, FeatureRecord) and isinstance(b, FeatureRecord)
        assert not hasattr(a, "entity_id") and not hasattr(a, "source")


def test_baseline_does_not_read_leaky_columns(fx):
    sub = fx.select("test")
    scrambled = {k: dataclasses.replace(r, source="x", id_type="x", entity_id="e0", name_kind="legal")
                 for k, r in fx.records.items()}
    assert rapidfuzz_scores(sub) == rapidfuzz_scores(BenchmarkData(scrambled, sub.pairs))


def test_identical_names_are_non_matches_in_this_release(fx):
    # documented in docs/format.md: matches always differ after case and punctuation folding
    same = [p for p, a, b in fx.iter_named_pairs() if simple_norm(a.name) == simple_norm(b.name)]
    assert same and all(p.label == 0 for p in same)
    res = evaluate(fx.select("test"), {p.pair_id: 0.5 for p in fx.pairs}, 0.5)
    assert res["by_identical_name"]["yes"]["tp"] == 0
    assert "cross_source" in res["by_categories"]
    assert sum(g["n"] for g in res["by_identical_name"].values()) == res["n_pairs"]


def _write(path, rows, bom=False):
    text = "pair_id,score\n" + "".join(f"{pid},{s}\n" for pid, s in rows)
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))


def _perfect(pairs):
    return [(p.pair_id, 0.9 if p.label else 0.1) for p in pairs]


def test_eval_refuses_test_only_file_without_threshold(tmp_path, capsys, fx):
    f = tmp_path / "test_only.csv"
    _write(f, _perfect(fx.select("test").pairs))
    assert main(["eval", str(f)]) == 2
    assert "no dev pairs" in capsys.readouterr().err
    assert main(["eval", str(f), "--threshold", "0.5", "--json"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["f1"] == 1.0 and res["threshold_from"] == "given"


def test_eval_refuses_unknown_ids(tmp_path, capsys):
    f = tmp_path / "wrong.csv"
    _write(f, [("zzz", 0.5)])
    assert main(["eval", str(f)]) == 2
    assert "no pair_id" in capsys.readouterr().err


def test_eval_dev_threshold_and_coverage(tmp_path, capsys, fx):
    f = tmp_path / "perfect.csv"
    _write(f, _perfect(fx.pairs))
    assert main(["eval", str(f), "--json"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["f1"] == 1.0 and res["threshold_from"] == "dev" and "oracle_threshold" not in res
    assert res["n_scored"] == res["n_pairs"]
    half = tmp_path / "half.csv"
    test = fx.select("test").pairs
    _write(half, _perfect(fx.select("dev").pairs) + _perfect(test[: len(test) // 2]))
    assert main(["eval", str(half)]) == 0
    cap = capsys.readouterr()
    assert "have no score" in cap.err and f"scored {len(test) // 2}" in cap.out
    assert main(["eval", str(half), "--missing", "error"]) == 2


def test_eval_reads_utf8_bom(tmp_path, capsys, fx):
    f = tmp_path / "bom.csv"
    _write(f, _perfect(fx.pairs), bom=True)
    assert main(["eval", str(f), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["f1"] == 1.0


def test_read_scores_strips_bom():
    import io
    assert read_scores(io.StringIO("﻿pair_id,score\np1,0.5\n")) == {"p1": 0.5}
