"""Run every reference baseline on dev+test of a data directory and write the leaderboard.

Usage: python scripts/run_baselines.py DATA_DIR OUT_DIR [baseline ...]

Thresholds are chosen on dev (best F1) and applied to test, as in docs/metrics.md.
Writes OUT_DIR/<baseline>.scores.csv, OUT_DIR/results.json and prints a Markdown table.
"""
import json
import os
import sys
import time

from usorg_bench import best_threshold, evaluate, load_dir
from usorg_bench.baselines import BASELINES


def main():
    data_dir, out = sys.argv[1], sys.argv[2]
    names = sys.argv[3:] or list(BASELINES)
    os.makedirs(out, exist_ok=True)
    d = load_dir(data_dir)
    sub = d.select(None)
    sub.pairs = [p for p in d.pairs if p.split in ("dev", "test")]
    dev, test = d.select("dev"), d.select("test")
    path = os.path.join(out, "results.json")
    results = json.load(open(path)) if os.path.exists(path) else {}
    for name in names:
        t0 = time.time()
        scores = {k: round(v, 6) for k, v in BASELINES[name](sub).items()}  # as written to the scores file
        secs = time.time() - t0
        with open(os.path.join(out, f"{name}.scores.csv"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("pair_id,score\n")
            for pid in sorted(scores):
                fh.write(f"{pid},{scores[pid]:.6f}\n")
        thr, _ = best_threshold([p.label for p in dev.pairs], [scores[p.pair_id] for p in dev.pairs])
        res = evaluate(test, scores, thr)
        res["seconds_dev_plus_test"] = round(secs, 1)
        results[name] = res
        print(f"{name}: F1 {res['f1']:.4f} AP {res['average_precision']:.4f} thr {thr:.4f} ({secs:.0f}s)", flush=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(results, fh, indent=1)
    print("\n| baseline | fields | test F1 | precision | recall | AP | F1 easy | F1 medium | F1 hard |")
    print("|---|---|---|---|---|---|---|---|---|")
    fields = {"rapidfuzz": "name", "logicv2": "name", "logicv2_full": "name + address", "splink": "name + city, state, ZIP"}
    for name, r in results.items():
        bd = r["by_difficulty"]
        print(f"| {name} | {fields.get(name, '')} | {r['f1']:.3f} | {r['precision']:.3f} | {r['recall']:.3f} | "
              f"{r['average_precision']:.3f} | {bd['easy']['f1']:.3f} | {bd['medium']['f1']:.3f} | {bd['hard']['f1']:.3f} |")


if __name__ == "__main__":
    main()
