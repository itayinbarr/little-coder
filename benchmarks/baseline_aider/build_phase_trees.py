"""Build phase1 (run-1 passes, 104 exercises) and phase2 (remainder, 121)
exercise trees from the full polyglot-benchmark. Both mirror the
<lang>/exercises/practice/<name>/ layout expected by Aider benchmark.py.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "polyglot-benchmark"
RUN1 = json.loads((HERE / "run1_passes.json").read_text())
P1 = HERE / "phase1-tree"
P2 = HERE / "phase2-tree"


def main() -> None:
    for d in (P1, P2):
        if d.exists():
            shutil.rmtree(d)

    c1 = c2 = 0
    for lang_dir in sorted(SRC.iterdir()):
        if not lang_dir.is_dir():
            continue
        lang = lang_dir.name
        practice = lang_dir / "exercises" / "practice"
        if not practice.is_dir():
            continue
        pass_set = set(RUN1.get(lang, []))
        for ex_dir in sorted(practice.iterdir()):
            if not ex_dir.is_dir():
                continue
            dst_root = P1 if ex_dir.name in pass_set else P2
            dst = dst_root / lang / "exercises" / "practice" / ex_dir.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(ex_dir, dst)
            if dst_root is P1:
                c1 += 1
            else:
                c2 += 1

    print(f"phase1: {c1} exercises (run-1 passes)")
    print(f"phase2: {c2} exercises (remainder)")
    for phase, d in (("phase1", P1), ("phase2", P2)):
        for lang_dir in sorted(d.iterdir()):
            n = len(list((lang_dir / "exercises" / "practice").iterdir()))
            print(f"  {phase}/{lang_dir.name}: {n}")


if __name__ == "__main__":
    main()
