import io
from collections import defaultdict

import pytest

from usorg_bench import load
from usorg_bench.data import CONFIDENCES, DIFFICULTIES, SPLITS, manifest, read_pairs, read_records, read_scores

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402


@pytest.fixture(scope="module")
def fx():
    return load("fixture")


def test_fixture_size_matches_manifest(fx):
    m = manifest()
    assert len(fx.pairs) == m["fixture"]["pairs"] == 5000
    assert len(fx.records) == m["fixture"]["records"]


def test_labels_are_identifier_equality(fx):
    # the whole benchmark rests on this: a pair matches iff both records carry the same identifier
    for p, a, b in fx.iter_named_pairs():
        assert a.id_type == b.id_type == p.id_type
        assert (a.entity_id == b.entity_id) == bool(p.label)
        assert a.record_id != b.record_id


def test_enumerations(fx):
    for p in fx.pairs:
        assert p.split in SPLITS
        assert p.difficulty in DIFFICULTIES
        assert p.label_confidence in CONFIDENCES
        assert 0.0 <= p.name_sim <= 100.0


def test_splits_are_entity_disjoint(fx):
    where = defaultdict(set)
    for p, a, b in fx.iter_named_pairs():
        where[a.entity_id].add(p.split)
        where[b.entity_id].add(p.split)
    assert all(len(s) == 1 for s in where.values())


def test_no_identifier_values_in_records(fx):
    for r in fx.records.values():
        assert r.entity_id.startswith("e") and len(r.entity_id) == 15
        assert r.record_id.startswith("r") and len(r.record_id) == 13


def test_select(fx):
    test = fx.select("test", confidence=["high"])
    assert test.pairs and all(p.split == "test" and p.label_confidence == "high" for p in test.pairs)
    with pytest.raises(ValueError):
        fx.select("validation")


def test_readers_reject_bad_input():
    good = "record_id,source,name,name_kind,address,city,state,zip5,id_type,entity_id\nr1,s,A,legal,,,,,uei,e1\n"
    recs = read_records(io.StringIO(good))
    with pytest.raises(ValueError):
        read_records(io.StringIO(good + "r1,s,B,legal,,,,,uei,e2\n"))
    hdr = "pair_id,left_id,right_id,label,id_type,label_confidence,difficulty,categories,name_sim,split\n"
    with pytest.raises(ValueError):
        read_pairs(io.StringIO(hdr + "p1,r1,r9,1,uei,high,easy,,99,test\n"), recs)
    with pytest.raises(ValueError):
        read_pairs(io.StringIO(hdr + "p1,r1,r1,2,uei,high,easy,,99,test\n"), recs)


def test_read_scores_valid():
    s = read_scores(io.StringIO("pair_id,score\na,0\nb,1\nc,0.25\n"))
    assert s == {"a": 0.0, "b": 1.0, "c": 0.25}


@pytest.mark.parametrize("bad", [
    "pair_id,score\na,1.5\n", "pair_id,score\na,-0.1\n", "pair_id,score\na,nan\n", "pair_id,score\na,inf\n",
    "pair_id,score\na,x\n", "pair_id,score\n,0.1\n", "pair_id,score\na,0.1\na,0.2\n", "id,score\na,0.1\n", "",
])
def test_read_scores_rejects(bad):
    with pytest.raises(ValueError):
        read_scores(io.StringIO(bad))


@settings(max_examples=500, deadline=None)
@given(st.text(max_size=300))
def test_read_scores_fuzz_never_crashes(text):
    # untrusted submission text: either parses into valid scores or raises ValueError
    try:
        out = read_scores(io.StringIO("pair_id,score\n" + text))
    except ValueError:
        return
    assert all(0.0 <= v <= 1.0 for v in out.values())
    assert all(k for k in out)


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=300))
def test_read_records_fuzz_never_crashes(text):
    hdr = "record_id,source,name,name_kind,address,city,state,zip5,id_type,entity_id\n"
    try:
        read_records(io.StringIO(hdr + text))
    except ValueError:
        pass
