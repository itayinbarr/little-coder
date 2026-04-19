"""Sample 50 exercises from run 3's passing set, stratified by language.

Input: benchmarks/results_full_polyglot_run2.json
Output: benchmarks/baseline_aider/baseline_sample_50.json

Stratification target sizes (proportional to run-3 pass counts, rounded to sum 50):
  python=9, go=7, rust=4, javascript=11, cpp=6, java=13.  Total=50.
Seed: 20260416.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "benchmarks" / "results_full_polyglot_run2.json"
OUT = ROOT / "benchmarks" / "baseline_aider" / "baseline_sample_50.json"

TARGETS = {
    "python": 9,
    "go": 7,
    "rust": 4,
    "javascript": 11,
    "cpp": 6,
    "java": 13,
}
SEED = 20260416


def main() -> None:
    data = json.loads(SRC.read_text())
    rng = random.Random(SEED)
    sample: dict[str, list[dict]] = {}
    for lang, target in TARGETS.items():
        passed = [
            {"name": d["name"], "status": d["status"], "turns": d.get("turns"), "time": d.get("time")}
            for d in data["languages"][lang]["details"]
            if str(d.get("status", "")).startswith("pass")
        ]
        if len(passed) < target:
            raise SystemExit(
                f"{lang}: only {len(passed)} passes in run 3, target {target}"
            )
        chosen = rng.sample(passed, target)
        chosen.sort(key=lambda x: x["name"])
        sample[lang] = chosen

    total = sum(len(v) for v in sample.values())
    assert total == 50, total

    OUT.write_text(json.dumps(
        {"seed": SEED, "targets": TARGETS, "total": total, "languages": sample},
        indent=2,
    ))
    print(f"wrote {OUT} ({total} exercises)")
    for lang, items in sample.items():
        names = ", ".join(x["name"] for x in items)
        print(f"  {lang} ({len(items)}): {names}")


if __name__ == "__main__":
    main()
