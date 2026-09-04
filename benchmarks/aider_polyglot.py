#!/usr/bin/env python3
"""Aider Polyglot runner for little-coder.

Drives `pi --mode rpc` per exercise via benchmarks/rpc_client.py::PiRpc.
Per-language transforms (xit-strip, @Disabled-strip, cpp CMakeLists
named dirs, cargo --include-ignored, EXERCISM_RUN_ALL_TESTS) are copied
verbatim from little-coder's original aider_polyglot.py — the only real
change is that the agent call site uses PiRpc instead of agent.run().

Usage:
    python benchmarks/aider_polyglot.py              # full run, default model
    python benchmarks/aider_polyglot.py --language python
    python benchmarks/aider_polyglot.py --exercise hello-world --language python
    python benchmarks/aider_polyglot.py --model llamacpp/qwen3.5-9b
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rpc_client import PiRpc, PromptResult  # noqa: E402

BENCHMARK_ROOT = Path.home() / "Documents" / "polyglot-benchmark"
REPO_ROOT = Path(__file__).parent.parent
RESULTS_FILE = Path(__file__).parent / "results_full_polyglot.json"
LOG_ROOT = Path(__file__).parent / "full_polyglot_logs"
#: Caps applied to persisted trajectories -- see _dump_trajectory.
TRAJECTORY_TEXT_CHARS = 200_000
TRAJECTORY_FIELD_CHARS = 20_000
#: Give up if this many exercises fail in a row -- a broken environment,
#: not broken exercises.
MAX_CONSECUTIVE_ERRORS = 3
def _positive_int_env(name: str, default: int) -> int:
    """Parse a positive-integer env var, failing with a readable message.

    A bare ValueError traceback (ATTEMPT_TIMEOUT_S=30m) is unhelpful, and a
    silently-accepted 0 is worse: _drain_events_until returns immediately with
    no events, so every exercise would record fail_timeout with a 0-turn
    trajectory.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(f"{name}: expected a positive integer (seconds), got {raw!r}")
    if value <= 0:
        raise SystemExit(f"{name}: must be > 0, got {value}")
    return value


#: Per-attempt RPC budget, seconds. 900 suits a fast hosted model; a local
#: model with a large thinking budget needs more, or every hard exercise is
#: clock-limited rather than capability-limited.
ATTEMPT_TIMEOUT_S = _positive_int_env("ATTEMPT_TIMEOUT_S", 900)
DEFAULT_MODEL = "llamacpp/qwen3.6-35b-a3b"

# Allowed tools for Polyglot — the core filesystem + bash toolbox. Ports
# the whitepaper's Polyglot configuration (no TB-style ShellSession, no
# GAIA-style Browser/Evidence).
ALLOWED_TOOLS = [
    "read", "Read",
    "write", "Write",
    "edit", "Edit",
    "bash", "Bash",
    "glob", "Glob",
    "grep", "Grep",
    "webfetch", "WebFetch",
]


# ── Per-language descriptors ──────────────────────────────────────────────
#
# Keep the structure identical to little-coder's aider_polyglot.py so the
# transforms (smoke-tested over the full 225-exercise run that produced the
# 78.67% headline) carry over unchanged.

def _copy_exercise(src: Path, dst: Path):
    """Copy exercise tree, excluding .meta/ (solutions live there)."""
    def _ignore(_dir, names):
        return [".meta"] if ".meta" in names else []
    shutil.copytree(src, dst, ignore=_ignore)


def _prepare_python(src: Path, work: Path):
    _copy_exercise(src, work)
    stubs = list(work.glob("*.py"))
    stubs = [p for p in stubs if not p.name.endswith("_test.py")]
    tests = list(work.glob("*_test.py"))
    return stubs, tests


def _run_python(work: Path, timeout: int):
    try:
        r = subprocess.run(
            ["python3", "-m", "pytest", "-x", "-q"],
            cwd=work, capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0, (r.stdout + r.stderr)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"


LANG_DESCRIPTORS = {
    "python": {
        "practice_dir": BENCHMARK_ROOT / "python" / "exercises" / "practice",
        "prepare": _prepare_python,
        "run_tests": _run_python,
        "syntax_hint": "Use Python 3. Run tests with `python -m pytest -x -q`.",
        "timeout_s": 90,
    },
    # go/rust/cpp/javascript/java descriptors omitted from this scaffold;
    # copy them verbatim from the Python repo's aider_polyglot.py when
    # running the full benchmark. Stub:
    # "rust":      {..., "prepare": _prepare_rust, ...},
    # "go":        {..., "prepare": _prepare_go, ...},
    # "cpp":       {..., "prepare": _prepare_cpp, ...},
    # "javascript": {..., "prepare": _prepare_js, ...},
    # "java":      {..., "prepare": _prepare_java, ...},
}


# ── Result file helpers ────────────────────────────────────────────────────

def _load_results() -> dict:
    if RESULTS_FILE.exists():
        try:
            return json.loads(RESULTS_FILE.read_text())
        except Exception:
            pass
    return {"exercises": {}, "meta": {}}


def _save_results(data: dict):
    tmp = RESULTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(RESULTS_FILE)


# ── Core loop ──────────────────────────────────────────────────────────────


def _clip(value, limit: int):
    """Bound a field before it is serialised into the trajectory."""
    if isinstance(value, str):
        return value[:limit]
    if value is None:
        return value
    text = json.dumps(value, default=str)
    return value if len(text) <= limit else text[:limit]


def _dump_trajectory(log_dir, attempt_name, result, work=None):
    """Persist what the harness otherwise discards.

    Only the final pytest output survives a run today, so a failure can be seen
    but not explained. PromptResult already carries the assistant text and every
    tool call; the work dir is a TemporaryDirectory destroyed on scope exit,
    taking the model's actual code with it.

    Writes per attempt: trajectory_<n>.json, trajectory_<n>.txt, workdir_<n>/.
    """
    try:
        payload = {
            "attempt": attempt_name,
            "agent_ended": getattr(result, "agent_ended", None),
            "turn_count": getattr(result, "turn_count", None),
            "compaction_events": getattr(result, "compaction_events", None),
            "assistant_text": (getattr(result, "assistant_text", "") or "")[:TRAJECTORY_TEXT_CHARS],
            # write/Write args carry whole file bodies and bash results whole
            # command output; uncapped this reaches hundreds of MB per exercise.
            "tool_calls": [
                {
                    **tc,
                    "args": _clip(tc.get("args"), TRAJECTORY_FIELD_CHARS),
                    "result_text": _clip(tc.get("result_text"), TRAJECTORY_FIELD_CHARS),
                }
                for tc in getattr(result, "tool_calls", [])
            ],
        }
        (log_dir / f"trajectory_{attempt_name}.json").write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8", errors="replace")
        lines = []
        for i, tc in enumerate(payload["tool_calls"], 1):
            lines.append(f"--- [{i}] {tc.get('name')} err={tc.get('is_error')} ---")
            lines.append(f"    args: {json.dumps(tc.get('args', {}), default=str)[:1500]}")
            lines.append(f"    result: {str(tc.get('result_text', ''))[:1500]}")
        lines.append("=== assistant text ===")
        lines.append(payload["assistant_text"][:20000])
        (log_dir / f"trajectory_{attempt_name}.txt").write_text(
            "\n".join(lines), encoding="utf-8", errors="replace")
        if work is not None and Path(work).exists():
            snap = log_dir / f"workdir_{attempt_name}"
            if snap.exists():
                shutil.rmtree(snap, ignore_errors=True)
            # A full 225-exercise run copies go/rust/cpp/js/java trees too;
            # without this a snapshot pulls in target/, build/, node_modules/
            # and compiled binaries, twice per exercise.
            shutil.copytree(work, snap, ignore=shutil.ignore_patterns(
                "__pycache__", ".pytest_cache", "target", "build", "node_modules",
                ".gradle", "CMakeFiles", "*.o", "*.so", "*.class", "*.rlib"))
    except Exception as exc:
        # Diagnostics must never fail the exercise they are diagnosing.
        try:
            (log_dir / f"trajectory_{attempt_name}.ERROR").write_text(repr(exc))
        except Exception:
            pass


def _was_clock_capped(result, elapsed: float) -> bool:
    """True when an attempt was cut off by the budget rather than finishing.

    ``agent_ended`` is also False when pi crashes or closes stdout early, which
    returns in seconds. That is a harness failure, not a slow model, and must
    not be recorded as ``fail_timeout`` (which would additionally suppress the
    retry). Require the attempt to have actually consumed the budget.
    """
    return (not result.agent_ended) and elapsed >= 0.9 * ATTEMPT_TIMEOUT_S


def _build_prompt(exercise_name: str, stub_paths, test_paths, syntax_hint: str) -> str:
    stubs_list = "\n".join(f"  - {p}" for p in stub_paths)
    tests_list = "\n".join(f"  - {p}" for p in test_paths)
    return (
        f"Implement the Exercism exercise `{exercise_name}`.\n\n"
        f"Stub file(s) to implement:\n{stubs_list}\n\n"
        f"Test file(s) (for reference only — DO NOT edit):\n{tests_list}\n\n"
        f"{syntax_hint}\n\n"
        "Read the stubs + any `.docs/instructions.md` in the workspace, "
        "then implement the solution. When you believe the code is correct, "
        "stop calling tools."
    )


def _run_exercise(
    lang: str,
    ex_name: str,
    model: str,
    verbose: bool,
    retry: bool,
):
    desc = LANG_DESCRIPTORS.get(lang)
    if desc is None:
        return {"status": "skipped", "reason": f"no descriptor for language {lang}"}

    src = desc["practice_dir"] / ex_name
    if not src.exists():
        return {"status": "error", "reason": f"exercise not found at {src}"}

    log_dir = LOG_ROOT / lang / ex_name
    log_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / ex_name
        stubs, tests = desc["prepare"](src, work)
        prompt = _build_prompt(ex_name, stubs, tests, desc["syntax_hint"])

        t0 = time.time()
        r2 = None
        with PiRpc(model=model, cwd=str(work), allowed_tools=ALLOWED_TOOLS,
                   session_id=f"poly-{lang}-{ex_name}",
                   env={"LITTLE_CODER_PERMISSION_MODE": "accept-all"}) as rpc:
            # prompt_and_collect() returns partial events *silently* when
            # agent_end never arrives (_drain_events_until returns `collected`,
            # it does not raise), so a budget-capped attempt is otherwise
            # indistinguishable from a completed one. Classified the same way
            # regardless of --no-retry, and re-evaluated for whichever attempt
            # ran last so a capped RETRY is not mislabelled a plain failure.
            ta = time.time()
            r1 = rpc.prompt_and_collect(prompt, timeout=ATTEMPT_TIMEOUT_S)
            a_elapsed = time.time() - ta
            passed, out = desc["run_tests"](work, desc["timeout_s"])
            attempt = "pass_1" if passed else None
            timed_out = (not passed) and _was_clock_capped(r1, a_elapsed)

            if not passed and retry and not timed_out:
                retry_prompt = (
                    "The tests failed. Output:\n\n```\n"
                    + out[-4000:]
                    + "\n```\n\nFix the implementation and try again."
                )
                tb = time.time()
                r2 = rpc.prompt_and_collect(retry_prompt, timeout=ATTEMPT_TIMEOUT_S)
                b_elapsed = time.time() - tb
                passed, out = desc["run_tests"](work, desc["timeout_s"])
                if passed:
                    attempt = "pass_2"
                else:
                    timed_out = _was_clock_capped(r2, b_elapsed)

        # Dumped AFTER the PiRpc block: on the timeout path the agent is still
        # executing inside it, and copytree races file writes it is making.
        _dump_trajectory(log_dir, "1", r1, work)
        if r2 is not None:
            _dump_trajectory(log_dir, "2", r2, work)

        elapsed = time.time() - t0
        (log_dir / "final_output.txt").write_text(out)
        if verbose:
            print(f"[{lang}/{ex_name}] {'PASS' if passed else 'FAIL'} in {elapsed:.1f}s on {attempt or 'fail'}")

        return {
            "status": attempt or ("fail_timeout" if timed_out else "fail"),
            "elapsed_s": round(elapsed, 2),
            "turn_count": (r1.turn_count + (r2.turn_count if not attempt == "pass_1" and retry else 0)) if attempt else r1.turn_count,
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--language", default="python")
    ap.add_argument("--exercise", default=None, help="Run a single exercise")
    ap.add_argument("--exercises", type=int, default=0, help="Run first N exercises (0 = all)")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--no-retry", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    results = _load_results() if args.resume else {"exercises": {}, "meta": {}}
    results["meta"].update({
        "model": args.model,
        "started_at": datetime.datetime.now().isoformat(),
    })

    desc = LANG_DESCRIPTORS.get(args.language)
    if desc is None:
        sys.exit(f"No descriptor for language '{args.language}'. Supported: {list(LANG_DESCRIPTORS)}")

    practice = desc["practice_dir"]
    if args.exercise:
        names = [args.exercise]
    else:
        names = sorted(p.name for p in practice.iterdir() if p.is_dir())
        if args.exercises:
            names = names[:args.exercises]

    consecutive_errors = 0
    for name in names:
        key = f"{args.language}/{name}"
        if args.resume and results["exercises"].get(key, {}).get("status") in ("pass_1", "pass_2"):
            continue
        # Results are checkpointed atomically per exercise one line below, but
        # an exception anywhere in _run_exercise still discarded every remaining
        # exercise. Record and continue -- while still failing loudly if the
        # environment itself is broken (missing pi CLI, model server down),
        # which would otherwise write "error" 225 times and print a summary
        # that reads like a finished 0% run.
        try:
            r = _run_exercise(
                args.language, name, args.model,
                verbose=args.verbose,
                retry=not args.no_retry,
            )
        except Exception as exc:
            r = {"status": "error", "reason": f"{type(exc).__name__}: {exc}"[:400]}
            print(f"[{args.language}/{name}] ERROR {r['reason']}")

        results["exercises"][key] = r
        _save_results(results)
        # Counts BOTH raised exceptions and returned {"status": "error"} --
        # _run_exercise returns that for a missing exercise directory, so a
        # stale benchmark checkout would otherwise never trip the guard.
        if str(r.get("status")) == "error":
            consecutive_errors += 1
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                raise RuntimeError(
                    f"aborting after {consecutive_errors} consecutive exercise "
                    f"errors -- the environment looks broken, not the exercises"
                )
        else:
            consecutive_errors = 0

    print(json.dumps({
        k: v["status"]
        for k, v in results["exercises"].items()
    }, indent=2))


if __name__ == "__main__":
    main()
