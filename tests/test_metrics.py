"""Metric definitions checked against scikit-learn (the reference implementation)."""
import math
import random

import pytest

from usorg_bench.metrics import average_precision, best_threshold, prf

sk = pytest.importorskip("sklearn.metrics")
hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402


def _rand(n, seed, ties=False):
    rng = random.Random(seed)
    ys = [rng.randint(0, 1) for _ in range(n)]
    ss = [round(rng.random(), 1 if ties else 6) for _ in range(n)]
    return ys, ss


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("ties", [False, True])
def test_average_precision_matches_sklearn(seed, ties):
    ys, ss = _rand(200, seed, ties)
    if sum(ys) == 0:
        ys[0] = 1
    assert math.isclose(average_precision(ys, ss), sk.average_precision_score(ys, ss), rel_tol=1e-12, abs_tol=1e-12)


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("thr", [0.0, 0.3, 0.5, 0.9, 1.0])
def test_prf_matches_sklearn(seed, thr):
    ys, ss = _rand(150, seed)
    pred = [int(s >= thr) for s in ss]
    p, r, f, _ = sk.precision_recall_fscore_support(ys, pred, average="binary", zero_division=0)
    m = prf(ys, ss, thr)
    assert math.isclose(m["precision"], p) and math.isclose(m["recall"], r) and math.isclose(m["f1"], f)
    assert math.isclose(m["accuracy"], sk.accuracy_score(ys, pred))


@settings(max_examples=300, deadline=None)
@given(st.lists(st.tuples(st.integers(0, 1), st.floats(0, 1, allow_nan=False)), min_size=1, max_size=60))
def test_best_threshold_is_optimal(rows):
    ys = [y for y, _ in rows]
    ss = [s for _, s in rows]
    t, f = best_threshold(ys, ss)
    assert 0.0 <= f <= 1.0
    assert math.isclose(prf(ys, ss, t)["f1"], f, abs_tol=1e-12)
    for cand in set(ss):  # no observed score as threshold does better
        assert prf(ys, ss, cand)["f1"] <= f + 1e-12


@settings(max_examples=300, deadline=None)
@given(st.lists(st.tuples(st.integers(0, 1), st.floats(0, 1, allow_nan=False)), min_size=1, max_size=60))
def test_average_precision_property(rows):
    ys = [y for y, _ in rows]
    ss = [s for _, s in rows]
    ap = average_precision(ys, ss)
    assert 0.0 <= ap <= 1.0 + 1e-12
    if sum(ys):
        assert math.isclose(ap, sk.average_precision_score(ys, ss), abs_tol=1e-9)
    else:
        assert ap == 0.0


def test_perfect_and_inverted_scores():
    ys = [1, 1, 0, 0]
    assert average_precision(ys, [0.9, 0.8, 0.2, 0.1]) == 1.0
    assert prf(ys, [0.9, 0.8, 0.2, 0.1], 0.5)["f1"] == 1.0
    assert prf(ys, [0.1, 0.2, 0.8, 0.9], 0.5)["f1"] == 0.0
