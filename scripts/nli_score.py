"""Score (premise, hypothesis) pairs with the local MNLI cross-encoder.

Runs as its own short-lived process and imports nothing heavier than torch, so
it can work on a memory-constrained machine. Checkpoints to the score cache
after every chunk, so a crash costs one chunk and rerunning resumes.

  py -3.12 scripts/detect.py --runs R --emit-pairs      # writes R_pairs.jsonl
  py -3.12 scripts/nli_score.py --pairs runs/R_pairs.jsonl
  py -3.12 scripts/nli_score.py --pairs runs/R_pairs.jsonl   # again, to resume
  py -3.12 scripts/detect.py --runs R                   # consumes the cache

If the process dies with an access violation rather than a Python error, that is
the safetensors memory-map failing under memory pressure. Rerun; progress is
kept. `--chunk` lowers the per-pass footprint.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from petal.detector import NliScoreCache, NliScorer, pair_key


def read_pairs(path: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            k = pair_key(rec["premise"], rec["hypothesis"])
            if k not in seen:
                seen.add(k)
                out.append((rec["premise"], rec["hypothesis"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--cache", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--chunk", type=int, default=250,
                    help="pairs scored between checkpoints")
    ap.add_argument("--max", type=int, default=0, help="stop after N new pairs")
    ap.add_argument("--batch", type=int, default=8)
    args = ap.parse_args()

    pairs_path = Path(args.pairs)
    cache_path = Path(args.cache) if args.cache else Path(
        str(pairs_path).replace("_pairs.jsonl", "") + "_nli.jsonl")

    # config is read without importing the rest of the package
    model = args.model
    if not model:
        cfgp = Path(__file__).resolve().parent.parent / "config.json"
        model = (json.loads(cfgp.read_text(encoding="utf-8")).get("nli_model")
                 if cfgp.exists() else None) or "typeform/distilbert-base-uncased-mnli"

    cache = NliScoreCache(cache_path)
    pairs = read_pairs(pairs_path)
    todo = [p for p in pairs if not cache.has(*p)]
    print("pairs %d, cached %d, to score %d" % (len(pairs), len(cache), len(todo)))
    if args.max:
        todo = todo[:args.max]
    if not todo:
        print("nothing to do; cache is complete for this pairs file.")
        return 0

    scorer = NliScorer(model, batch_size=args.batch)
    t0 = time.time()
    done = 0
    for s in range(0, len(todo), args.chunk):
        chunk = todo[s:s + args.chunk]
        scores = scorer.score_pairs(chunk)
        cache.append([(pair_key(p, h), v) for (p, h), v in zip(chunk, scores)])
        done += len(chunk)
        el = time.time() - t0
        rate = done / el if el else 0.0
        print("  %5d/%d  %.1f pairs/s  eta %.0fs"
              % (done, len(todo), rate, (len(todo) - done) / rate if rate else 0))
    print("done in %.0fs; cache now holds %d pairs -> %s"
          % (time.time() - t0, len(cache), cache_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
