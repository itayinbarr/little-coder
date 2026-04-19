"""Build a filtered polyglot-benchmark tree containing only the sampled 50 exercises.

Reads baseline_sample_50.json, copies matching exercise dirs from polyglot-benchmark/
into filtered-polyglot-benchmark/ preserving <lang>/exercises/practice/<name>/ layout.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "polyglot-benchmark"
DST = HERE / "filtered-polyglot-benchmark"
SAMPLE = HERE / "baseline_sample_50.json"


def main() -> None:
    sample = json.loads(SAMPLE.read_text())
    if DST.exists():
        shutil.rmtree(DST)
    count = 0
    for lang, items in sample["languages"].items():
        for it in items:
            name = it["name"]
            src = SRC / lang / "exercises" / "practice" / name
            dst = DST / lang / "exercises" / "practice" / name
            if not src.is_dir():
                raise SystemExit(f"missing: {src}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
            count += 1
    print(f"copied {count} exercise dirs into {DST}")


if __name__ == "__main__":
    main()
