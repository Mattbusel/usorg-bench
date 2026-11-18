"""Command line: ``usorg-bench {info,eval,baseline,export}``."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from . import __version__
from .data import load, load_dir, read_scores
from .metrics import best_threshold, evaluate


def _data(args):
    d = load_dir(args.data_dir) if getattr(args, "data_dir", None) else load(args.which)
    conf = args.confidence.split(",") if getattr(args, "confidence", None) else None
    return d, conf


def _summary(res: dict) -> str:
    lines = [f"pairs {res['n_pairs']}  scored {res['n_scored']}  threshold {res['threshold']:.4f}"
             f"{' (best F1 on these pairs, not a leaderboard number)' if res.get('oracle_threshold') else ''}"
             f"{' (from dev)' if res.get('threshold_from') == 'dev' else ''}",
             f"precision {res['precision']:.4f}  recall {res['recall']:.4f}  F1 {res['f1']:.4f}  "
             f"AP {res['average_precision']:.4f}"]
    for k in ("by_difficulty", "by_id_type", "by_label_confidence", "by_categories", "by_identical_name"):
        for g, m in res.get(k, {}).items():
            lines.append(f"  {k[3:]:>16} {g:<14} n={m['n']:<6} P={m['precision']:.3f} R={m['recall']:.3f} "
                         f"F1={m['f1']:.3f} acc={m['accuracy']:.3f}")
    return "\n".join(lines)


def cmd_info(args) -> int:
    d, _ = _data(args)
    from collections import Counter
    c = Counter((p.split, p.label) for p in d.pairs)
    print(f"usorg-bench {__version__}: {len(d.records)} records, {len(d.pairs)} pairs")
    for s in ("train", "dev", "test"):
        print(f"  {s:5} matches={c[(s, 1)]} non-matches={c[(s, 0)]}")
    return 0


def _warn(msg: str) -> None:
    print(f"usorg-bench: warning: {msg}", file=sys.stderr)


def cmd_eval(args) -> int:
    d, conf = _data(args)
    with open(args.scores, encoding="utf-8-sig", newline="") as fh:  # -sig: Excel writes a BOM
        scores = read_scores(fh)
    target = d.select(args.split, confidence=conf)
    n_scored = sum(1 for p in target.pairs if p.pair_id in scores)
    if target.pairs and n_scored == 0:
        raise ValueError(f"no pair_id in {args.scores} belongs to the {args.split} split; "
                         f"check that the file scores this dataset (--which / --data-dir)")
    unknown = len(set(scores) - {p.pair_id for p in d.pairs})
    if unknown:
        _warn(f"{unknown} pair_ids in {args.scores} are not in this dataset and are ignored")
    if n_scored < len(target.pairs):
        _warn(f"{len(target.pairs) - n_scored} of {len(target.pairs)} {args.split} pairs have no score "
              f"(--missing {args.missing})")
    thr, thr_from = args.threshold, ("given" if args.threshold is not None else None)
    if thr is None and args.split == "test":
        dev = d.select("dev", confidence=conf)
        dev_scored = [p for p in dev.pairs if p.pair_id in scores]
        if not dev_scored:
            raise ValueError("the scores file has no dev pairs, so no threshold can be chosen on dev; "
                             "include dev scores or pass --threshold")
        if len(dev_scored) < len(dev.pairs):
            _warn(f"{len(dev.pairs) - len(dev_scored)} of {len(dev.pairs)} dev pairs have no score; "
                  f"the threshold is chosen on the {len(dev_scored)} scored dev pairs")
        thr, _ = best_threshold([p.label for p in dev_scored], [scores[p.pair_id] for p in dev_scored])
        thr_from = "dev"
    res = evaluate(target, scores, thr, missing=args.missing)
    if thr_from:
        res["threshold_from"] = thr_from
    print(json.dumps(res, indent=1) if args.json else _summary(res))
    return 0


def cmd_baseline(args) -> int:
    from .baselines import BASELINES
    d, conf = _data(args)
    sub = d.select(confidence=conf) if conf else d
    if args.split:
        sub = sub.select(args.split)
    scores = BASELINES[args.name](sub)
    out = sys.stdout if args.out == "-" else open(args.out, "w", encoding="utf-8", newline="")
    try:
        out.write("pair_id,score\n")
        for pid in sorted(scores):
            out.write(f"{pid},{scores[pid]:.6f}\n")
    finally:
        if out is not sys.stdout:
            out.close()
    return 0


def cmd_export(args) -> int:
    from . import export as ex
    from .data import BenchmarkData
    d, _ = _data(args)
    if args.split:  # keep the split's pairs and only the records they reference
        sub = d.select(args.split)
        used = {rid for p in sub.pairs for rid in (p.left_id, p.right_id)}
        d = BenchmarkData({k: v for k, v in d.records.items() if k in used}, sub.pairs)
    os.makedirs(args.out_dir, exist_ok=True)
    if args.format == "name_bench":
        rows = ex.name_bench_rows(d, n=args.n)
        with open(os.path.join(args.out_dir, "us_orgs_cases.csv"), "w", encoding="utf-8", newline="") as fh:
            ex.write_name_bench(rows, fh)
        print(f"{len(rows)} rows")
    elif args.format == "senzing":
        cl = ex.clean_clusters(d, args.id_type, max_entities=args.max_entities)
        with open(os.path.join(args.out_dir, "usorgs.jsonl"), "w", encoding="utf-8", newline="") as fr, \
                open(os.path.join(args.out_dir, "usorgs_truthset_key.csv"), "w", encoding="utf-8", newline="") as fk:
            n = ex.write_senzing(cl, fr, fk)
        print(f"{n} records in {len(cl)} clusters")
    elif args.format == "zingg":
        cl = ex.clean_clusters(d, args.id_type, max_entities=args.max_entities)
        with open(os.path.join(args.out_dir, "usOrgs.csv"), "w", encoding="utf-8", newline="") as fh:
            ex.write_csv(ex.zingg_rows(cl), ex.ZINGG_COLUMNS, fh)
        tr = ex.zingg_training_rows(d, cl)
        with open(os.path.join(args.out_dir, "training.csv"), "w", encoding="utf-8", newline="") as fh:
            ex.write_csv(tr, ("z_cluster", "z_isMatch") + ex.ZINGG_COLUMNS, fh)
        cfg = ex.zingg_config("examples/us-orgs/usOrgs.csv", "examples/us-orgs/training.csv")
        with open(os.path.join(args.out_dir, "config.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(cfg, fh, indent=2)
            fh.write("\n")
        print(f"{sum(len(v) for v in cl.values())} records, {len(tr) // 2} training pairs")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="usorg-bench", description="US organization matching benchmark")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--which", choices=("fixture", "full"), default="fixture")
        p.add_argument("--data-dir", help="directory with records.csv and pairs.csv (overrides --which)")
        p.add_argument("--confidence", help="comma-separated label_confidence tiers to keep")

    p = sub.add_parser("info", help="counts per split")
    common(p)
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("eval", help="score a pair_id,score CSV")
    common(p)
    p.add_argument("scores")
    p.add_argument("--split", choices=("train", "dev", "test"), default="test")
    p.add_argument("--threshold", type=float,
                   help="decision threshold; default: best F1 on dev when scoring test, else on the pairs scored")
    p.add_argument("--missing", choices=("zero", "error", "skip"), default="zero")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("baseline", help="run a reference baseline and write pair_id,score")
    common(p)
    p.add_argument("name", choices=("rapidfuzz", "logicv2", "logicv2_full", "splink"))
    p.add_argument("--split", choices=("train", "dev", "test"))
    p.add_argument("--out", default="-")
    p.set_defaults(func=cmd_baseline)

    p = sub.add_parser("export", help="write nomenklatura, Senzing or Zingg files")
    common(p)
    p.add_argument("format", choices=("name_bench", "senzing", "zingg"))
    p.add_argument("out_dir")
    p.add_argument("--split", choices=("train", "dev", "test"))
    p.add_argument("--n", type=int, default=300, help="name_bench rows")
    p.add_argument("--id-type", default="uei")
    p.add_argument("--max-entities", type=int)
    p.set_defaults(func=cmd_export)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, KeyError, OSError) as e:
        print(f"usorg-bench: error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
