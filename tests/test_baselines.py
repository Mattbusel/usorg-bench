import pytest

from usorg_bench import evaluate, load
from usorg_bench.baselines import BASELINES


@pytest.fixture(scope="module")
def small():
    d = load("fixture")
    return d.select("test")


@pytest.mark.parametrize("name,module", [("rapidfuzz", "rapidfuzz"), ("logicv2", "nomenklatura"),
                                         ("logicv2_full", "nomenklatura"), ("splink", "splink")])
def test_baseline_scores_every_pair(small, name, module):
    pytest.importorskip(module)
    scores = BASELINES[name](small)
    assert set(scores) == {p.pair_id for p in small.pairs}
    assert all(0.0 <= s <= 1.0 for s in scores.values())
    res = evaluate(small, scores)
    # every baseline must beat chance on the fixture
    assert res["average_precision"] > sum(p.label for p in small.pairs) / len(small.pairs)
