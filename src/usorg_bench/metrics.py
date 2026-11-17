"""Scoring for USORG-Bench submissions.

Definitions follow scikit-learn so results are comparable with other papers and tools:
``average_precision`` equals ``sklearn.metrics.average_precision_score`` and the threshold
metrics equal ``precision_recall_fscore_support(average="binary")`` with ``zero_division=0``.
The test suite checks both against scikit-learn.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .data import BenchmarkData, Pair


def confusion(labels: Sequence[int], scores: Sequence[float], threshold: float) -> Tuple[int, int, int, int]:
    """(tp, fp, tn, fn) with predicted match = score >= threshold."""
    tp = fp = tn = fn = 0
    for y, s in zip(labels, scores):
        pred = s >= threshold
        if y and pred:
            tp += 1
        elif y:
            fn += 1
        elif pred:
            fp += 1
        else:
            tn += 1
    return tp, fp, tn, fn


def prf(labels: Sequence[int], scores: Sequence[float], threshold: float) -> Dict[str, float]:
    tp, fp, tn, fn = confusion(labels, scores, threshold)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    n = tp + fp + tn + fn
    return {"precision": p, "recall": r, "f1": f, "accuracy": (tp + tn) / n if n else 0.0,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn, "n": n}


def average_precision(labels: Sequence[int], scores: Sequence[float]) -> float:
    """Area under the precision-recall curve as a step sum (scikit-learn's definition).

    Returns 0.0 when there are no positives (scikit-learn warns and returns 0 for that case too).
    """
    pairs = sorted(zip(scores, labels), key=lambda t: -t[0])
    total_pos = sum(1 for _, y in pairs if y)
    if total_pos == 0:
        return 0.0
    ap = 0.0
    tp = fp = 0
    prev_recall = 0.0
    i = 0
    n = len(pairs)
    while i < n:
        s = pairs[i][0]
        while i < n and pairs[i][0] == s:  # ties form one threshold
            if pairs[i][1]:
                tp += 1
            else:
                fp += 1
            i += 1
        recall = tp / total_pos
        precision = tp / (tp + fp)
        ap += (recall - prev_recall) * precision
        prev_recall = recall
    return ap


def best_threshold(labels: Sequence[int], scores: Sequence[float]) -> Tuple[float, float]:
    """The score threshold with the highest F1 and that F1. Ties go to the higher threshold."""
    pairs = sorted(zip(scores, labels), key=lambda t: -t[0])
    total_pos = sum(1 for _, y in pairs if y)
    if not pairs:
        return 0.5, 0.0
    best_t, best_f = pairs[0][0], -1.0
    tp = fp = 0
    i, n = 0, len(pairs)
    while i < n:
        s = pairs[i][0]
        while i < n and pairs[i][0] == s:
            if pairs[i][1]:
                tp += 1
            else:
                fp += 1
            i += 1
        p = tp / (tp + fp)
        r = tp / total_pos if total_pos else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        if f > best_f:
            best_t, best_f = s, f
    return best_t, max(best_f, 0.0)


def _collect(data: BenchmarkData, scores: Mapping[str, float], missing: str) -> Tuple[List[Pair], List[float]]:
    ps, ss = [], []
    for p in data.pairs:
        if p.pair_id in scores:
            ps.append(p)
            ss.append(float(scores[p.pair_id]))
        elif missing == "error":
            raise KeyError(f"no score for pair {p.pair_id}")
        elif missing == "zero":
            ps.append(p)
            ss.append(0.0)
    return ps, ss


def evaluate(data: BenchmarkData, scores: Mapping[str, float], threshold: Optional[float] = None, *,
             missing: str = "zero", by: Iterable[str] = ("difficulty", "id_type", "label_confidence")) -> dict:
    """Score a submission against the pairs in ``data``.

    ``scores`` maps pair_id to a score in [0, 1]. Pairs without a score count as 0.0 by default
    (``missing="zero"``); ``"error"`` raises and ``"skip"`` leaves them out. When ``threshold`` is
    None the best-F1 threshold on these same pairs is used and reported as ``oracle_threshold``;
    for the leaderboard pick the threshold on the dev split and pass it in for test.
    """
    if missing not in ("zero", "error", "skip"):
        raise ValueError("missing must be 'zero', 'error' or 'skip'")
    ps, ss = _collect(data, scores, missing)
    ys = [p.label for p in ps]
    out: dict = {"n_pairs": len(ps), "n_scored": sum(1 for p in data.pairs if p.pair_id in scores)}
    if threshold is None:
        threshold, _ = best_threshold(ys, ss)
        out["oracle_threshold"] = True
    out["threshold"] = threshold
    out.update(prf(ys, ss, threshold))
    out["average_precision"] = average_precision(ys, ss)
    for field in by:
        groups: Dict[str, Tuple[List[int], List[float]]] = {}
        for p, s in zip(ps, ss):
            g = groups.setdefault(str(getattr(p, field)), ([], []))
            g[0].append(p.label)
            g[1].append(s)
        out[f"by_{field}"] = {k: dict(prf(v[0], v[1], threshold), average_precision=average_precision(*v))
                              for k, v in sorted(groups.items())}
    return out
