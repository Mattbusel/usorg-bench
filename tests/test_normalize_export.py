import csv
import io
import json
import os

import pytest

from usorg_bench import load
from usorg_bench import export as ex
from usorg_bench.cli import main
from usorg_bench.normalize import is_acronym_of, legal_form, looks_like_person, name_key, simple_norm

GIVEN = {"JOHN", "MARY", "ROBERT", "MARTHA", "DON", "KIMBERLY"}


@pytest.mark.parametrize("name,key,form", [
    ("The Boeing Company", "BOEING", None),
    ("BOEING COMPANY, THE", "BOEING", None),
    ("ATOLLA TECH, INC.", "ATOLLA TECH", "CORP"),
    ("Atolla Tech L.L.C.", "ATOLLA TECH", "LLC"),
    ("S&P Global Inc", "S AND P GLOBAL", "CORP"),
    ("Smith Partners, LLP", "SMITH PARTNERS", "LP"),
])
def test_name_key_and_form(name, key, form):
    assert name_key(name) == key
    assert legal_form(name) == form


def test_simple_norm():
    assert simple_norm("Müller & Söhne, U.S.A.") == "MULLER AND SOHNE USA"


@pytest.mark.parametrize("name,person", [
    ("JOHN A SMITH", True), ("SMITH, JOHN A", True), ("Martha Whitman", True), ("WERDIGER MD NORMAN S", True),
    ("JOHN SMITH DBA SMITH PLUMBING", True), ("JOHN SMITH PLUMBING LLC", False), ("MARY'S BAKERY INC", False),
    ("CITY OF ROBERT", False), ("ROBERT HALF INTERNATIONAL", False), ("ACME", False),
])
def test_person_filter(name, person):
    assert looks_like_person(name, GIVEN) is person


def test_acronym():
    assert is_acronym_of("IBM", "International Business Machines Corp")
    assert is_acronym_of("UCF", "The University of Central Florida")
    assert not is_acronym_of("IBM", "Intel Corp")


@pytest.fixture(scope="module")
def fx():
    return load("fixture")


# header and value rules of nomenklatura contrib/name_bench/cases.csv (schema v1)
NB_HEADER = ["case_group", "schema", "name1", "name2", "is_match", "quality", "category", "notes"]


def test_name_bench_rows(fx):
    rows = ex.name_bench_rows(fx, n=120)
    assert len(rows) == 120
    buf = io.StringIO()
    ex.write_name_bench(rows, buf)
    parsed = list(csv.DictReader(io.StringIO(buf.getvalue())))
    assert list(parsed[0].keys()) == NB_HEADER
    assert sum(r["is_match"] == "true" for r in parsed) == 60
    for r in parsed:
        assert r["case_group"] == "us_orgs"
        assert r["schema"] in ("Company", "Organization")
        assert r["is_match"] in ("true", "false")
        assert r["quality"] in ("STRONG", "MEDIUM", "WEAK")
        assert simple_norm(r["name1"]) != simple_norm(r["name2"])
    assert len({(r["name1"], r["name2"]) for r in parsed}) == len(parsed)


def test_clean_clusters_have_no_shared_company_keys(fx):
    cl = ex.clean_clusters(fx, "uei")
    owner = {}
    for e, rs in cl.items():
        for r in rs:
            k = name_key(r.name)
            if not ex.GOV_WORDS.intersection(k.split()):
                assert owner.setdefault(k, e) == e
    assert all(r.id_type == "uei" for rs in cl.values() for r in rs)


def test_senzing_export(fx):
    cl = ex.clean_clusters(fx, "uei", max_entities=200)
    rec, key = io.StringIO(), io.StringIO()
    n = ex.write_senzing(cl, rec, key)
    lines = rec.getvalue().splitlines()
    assert n == len(lines) == sum(len(v) for v in cl.values())
    keyrows = list(csv.DictReader(io.StringIO(key.getvalue())))
    assert [list(keyrows[0].keys())] == [["CLUSTER_ID", "RECORD_ID", "DATA_SOURCE"]]
    ids = set()
    for line, k in zip(lines, keyrows):
        j = json.loads(line)
        assert set(j) == {"DATA_SOURCE", "RECORD_ID", "FEATURES"}
        assert j["FEATURES"][0] == {"RECORD_TYPE": "ORGANIZATION"}
        assert any("NAME_ORG" in f for f in j["FEATURES"])
        assert (j["DATA_SOURCE"], j["RECORD_ID"]) == (k["DATA_SOURCE"], k["RECORD_ID"])
        ids.add((j["DATA_SOURCE"], j["RECORD_ID"]))
    assert len(ids) == n


def test_zingg_export(fx):
    cl = ex.clean_clusters(fx, "uei", max_entities=200)
    tr = ex.zingg_training_rows(fx, cl, n_pairs=40)
    assert len(tr) % 2 == 0
    for a, b in zip(tr[::2], tr[1::2]):
        assert a["z_cluster"] == b["z_cluster"] and a["z_isMatch"] == b["z_isMatch"]
    assert {r["z_isMatch"] for r in tr} == {"0", "1"}  # Zingg refuses to train on one class
    cfg = ex.zingg_config("examples/us-orgs/usOrgs.csv", "examples/us-orgs/training.csv")
    names = [f["fieldName"] for f in cfg["fieldDefinition"]]
    assert names == list(ex.ZINGG_COLUMNS)
    assert cfg["data"][0]["schema"].split(", ")[0] == "id string"
    json.dumps(cfg)


def test_cli_roundtrip(tmp_path, capsys, fx):
    assert main(["info"]) == 0
    capsys.readouterr()
    out = tmp_path / "scores.csv"
    assert main(["baseline", "rapidfuzz", "--out", str(out)]) == 0
    assert main(["eval", str(out), "--json"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["n_pairs"] == sum(p.split == "test" for p in fx.pairs)
    assert 0.0 <= res["f1"] <= 1.0
    for fmt in ("name_bench", "senzing", "zingg"):
        assert main(["export", fmt, str(tmp_path / fmt), "--max-entities", "100", "--n", "50"]) == 0
    assert os.path.exists(tmp_path / "senzing" / "usorgs_truthset_key.csv")
    bad = tmp_path / "bad.csv"
    bad.write_text("pair_id,score\nx,2\n")
    assert main(["eval", str(bad)]) == 2
