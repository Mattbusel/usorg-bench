"""Reference baselines. Each returns ``{pair_id: score in [0, 1]}``.

* ``rapidfuzz`` - token-sort ratio of the normalized names (name only).
* ``logicv2`` - nomenklatura's LogicV2 matcher on FtM entities built from the name only, exactly
  as nomenklatura's ``contrib/name_bench`` harness builds them.
* ``logicv2_full`` - LogicV2 on entities that also carry the address, city, state and ZIP.
* ``splink`` - an unsupervised Splink model with Splink's default comparisons (NameComparison on
  the name, exact match on city, state and ZIP), u from random sampling and m by EM, scoring
  exactly the benchmark pairs.

rapidfuzz is a core dependency; nomenklatura and splink are optional extras
(``pip install usorg-bench[logicv2]`` / ``[splink]``).
"""
from __future__ import annotations

from typing import Callable, Dict

from .data import BenchmarkData, Record
from .normalize import legal_form, simple_norm


def rapidfuzz_scores(data: BenchmarkData) -> Dict[str, float]:
    from rapidfuzz import fuzz

    return {p.pair_id: fuzz.token_sort_ratio(simple_norm(a.name), simple_norm(b.name)) / 100.0
            for p, a, b in data.iter_named_pairs()}


def _ftm_schema(a: Record, b: Record) -> str:
    return "Company" if (legal_form(a.name) or legal_form(b.name)) else "Organization"


def _logicv2(data: BenchmarkData, with_address: bool) -> Dict[str, float]:
    from followthemoney import ValueEntity, model
    from nomenklatura.matching.logic_v2.model import LogicV2

    config = LogicV2.default_config()

    def entity(schema, r: Record, i: str):
        e = ValueEntity(model.get(schema), {"id": i})
        e.add("name", r.name)
        if with_address:
            e.add("country", "us")
            parts = [r.address, r.city, " ".join(x for x in (r.state, r.zip5) if x)]
            full = ", ".join(x for x in parts if x)
            if full:
                e.add("address", full)
        return e

    out = {}
    for p, a, b in data.iter_named_pairs():
        schema = _ftm_schema(a, b)
        res = LogicV2.compare(entity(schema, a, "l" + p.pair_id), entity(schema, b, "r" + p.pair_id), config)
        out[p.pair_id] = min(1.0, max(0.0, float(res.score)))
    return out


def logicv2_scores(data: BenchmarkData) -> Dict[str, float]:
    return _logicv2(data, with_address=False)


def logicv2_full_scores(data: BenchmarkData) -> Dict[str, float]:
    return _logicv2(data, with_address=True)


def splink_scores(data: BenchmarkData, seed: int = 20261117) -> Dict[str, float]:
    import pandas as pd
    import splink.comparison_library as cl
    from splink import DuckDBAPI, Linker, SettingsCreator, block_on

    used = {rid for p in data.pairs for rid in (p.left_id, p.right_id)}
    rows = []
    for rid in sorted(used):
        r = data.records[rid]
        rows.append({"unique_id": rid, "name": simple_norm(r.name) or None,
                     "city": simple_norm(r.city) if r.city else None, "state": r.state, "zip5": r.zip5})
    df = pd.DataFrame(rows)
    settings = SettingsCreator(
        link_type="dedupe_only",
        comparisons=[cl.NameComparison("name"), cl.ExactMatch("city"), cl.ExactMatch("state"),
                     cl.ExactMatch("zip5")],
        blocking_rules_to_generate_predictions=[block_on("state")],
        retain_matching_columns=False,
    )
    db = DuckDBAPI()
    linker = Linker(db.register(df), settings, log_level=40)
    linker.training.estimate_probability_two_random_records_match(
        [block_on("name")], recall=0.7)
    linker.training.estimate_u_using_random_sampling(max_pairs=2e6, seed=seed)
    linker.training.estimate_parameters_using_expectation_maximisation(block_on("state"))
    linker.training.estimate_parameters_using_expectation_maximisation(block_on("substr(name, 1, 4)"))
    blocked = pd.DataFrame({"match_key": "0",
                            "join_key_l": [p.left_id for p in data.pairs],
                            "join_key_r": [p.right_id for p in data.pairs]}).drop_duplicates(
        ["join_key_l", "join_key_r"])
    linker.table_management.register_blocked_pairs_for_predict(db.register(blocked))
    pred = linker.inference.predict().as_pandas_dataframe()
    prob = {}
    for l_, r_, mp in zip(pred.unique_id_l, pred.unique_id_r, pred.match_probability):
        prob[(l_, r_)] = prob[(r_, l_)] = float(mp)
    return {p.pair_id: prob.get((p.left_id, p.right_id), 0.0) for p in data.pairs}


BASELINES: Dict[str, Callable[[BenchmarkData], Dict[str, float]]] = {
    "rapidfuzz": rapidfuzz_scores,
    "logicv2": logicv2_scores,
    "logicv2_full": logicv2_full_scores,
    "splink": splink_scores,
}
