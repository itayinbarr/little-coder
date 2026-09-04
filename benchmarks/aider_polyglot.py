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
import uuid
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
#: Identifies one invocation, so records and artifacts can be traced back to the
#: run that produced them. RESULTS_FILE and LOG_ROOT are both deterministic and
#: shared across runs, which has already caused artifacts from different runs to
#: be compared as if they came from one.
RUN_ID = f"{datetime.datetime.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
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
        "score_in_copy": True,
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


def _purge_log_dir(log_dir: Path):
    """Remove artifacts from previous runs of this exercise.

    LOG_ROOT/<lang>/<exercise> is deterministic and nothing cleaned it, so a
    one-attempt rerun left the previous run's trajectory_2/workdir_2 sitting
    next to a fresh trajectory_1. Those pairs look like one run and are not:
    comparing them produced a confident, wrong conclusion during review.
    """
    for pattern in ("trajectory_*", "workdir_*", "final_output*"):
        for path in log_dir.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                try:
                    path.unlink()
                except OSError:
                    pass


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
            ignore = shutil.ignore_patterns(
                "__pycache__", ".pytest_cache", "target", "build", "node_modules",
                ".gradle", "CMakeFiles", "*.o", "*.so", "*.class", "*.rlib")
            # A file can vanish mid-walk while the agent is still active. One
            # retry beats losing the snapshot to the blanket except below,
            # which would leave only a .ERROR file for the very case the
            # snapshot exists to explain.
            for attempt_i in range(2):
                try:
                    shutil.copytree(work, snap, ignore=ignore)
                    break
                except FileNotFoundError:
                    shutil.rmtree(snap, ignore_errors=True)
                    if attempt_i == 1:
                        raise
                    time.sleep(0.5)
    except Exception as exc:
        # Diagnostics must never fail the exercise they are diagnosing.
        try:
            (log_dir / f"trajectory_{attempt_name}.ERROR").write_text(repr(exc))
        except Exception:
            pass


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



def _stop_reason(result) -> str:
    """Why an attempt ended: agent_end | deadline | process_exit.

    Shim, deliberately: if rpc_client predates PromptResult.stop_reason (or that
    change is reverted -- it has been once already), fall back to the old signal
    so scoring degrades instead of breaking.
    """
    reason = getattr(result, "stop_reason", None)
    if reason:
        return reason
    return "agent_end" if getattr(result, "agent_ended", False) else "deadline"


def _is_empty_response(result) -> bool:
    """pi finished the turn without doing anything.

    An empty completion from the provider: agent_end arrives, but no tool call,
    no turn of work and no assistant text. Six of sixteen recorded attempts in
    this repo's log tree look like this. Classified as agent_end they read as
    clean failures, hiding a provider-side fault behind a model-quality number.
    """
    return (
        getattr(result, "agent_ended", False)
        and (getattr(result, "turn_count", 0) or 0) <= 1
        and not getattr(result, "tool_calls", None)
        and not (getattr(result, "assistant_text", "") or "").strip()
    )


def _attempt_outcome(result) -> str:
    """One attempt's outcome, independent of whether the tests passed."""
    reason = _stop_reason(result)
    if reason in ("process_exit", "deadline"):
        return reason
    if _is_empty_response(result):
        return "empty_response"
    return "completed"


def _classify_status(passed: bool, attempt: str | None,
                     outcome_1: str, outcome_2: str | None = None) -> str:
    """Precedence for the recorded status. Pure, so it can be table-tested.

    `passed` wins over everything: a pi that exits right after writing a correct
    solution must not be downgraded from a pass to an error.
    """
    if passed:
        return attempt or "pass_1"
    last = outcome_2 if outcome_2 is not None else outcome_1
    if outcome_2 is None:
        # Only one attempt ran, so a dead process means the run itself failed.
        if outcome_1 == "process_exit":
            return "error"
    elif outcome_2 == "process_exit":
        # Attempt 1 was scored, so this is a failed exercise, not a broken run.
        return "fail"
    if last == "deadline":
        return "fail_timeout"
    if last == "empty_response":
        return "empty_response"
    return "fail"


def _score(desc, work: Path, timeout: int):
    """Run the tests against a COPY, so a live agent cannot influence the score.

    prompt_and_collect returning does not mean pi is finished: measured on three
    real exercises, pi still had a live child process at the moment the tests
    would start. Scoring a copy removes the race on every path, keeps the retry's
    session alive, and stops the test runner's droppings landing in the agent's
    tree. Not enabled for cpp/rust, whose build dirs are absolute-path-bound and
    would force a full rebuild per scoring pass.
    """
    if not desc.get("score_in_copy"):
        return desc["run_tests"](work, timeout)
    with tempfile.TemporaryDirectory() as scratch:
        target = Path(scratch) / work.name
        shutil.copytree(work, target)
        return desc["run_tests"](target, timeout)


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
    _purge_log_dir(log_dir)

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
            r1 = rpc.prompt_and_collect(prompt, timeout=ATTEMPT_TIMEOUT_S)
            outcome_1 = _attempt_outcome(r1)
            outcome_2 = None
            # Belt-and-braces: an attempt that did not end cleanly may still
            # have work in flight. Stop it before anything reads the tree.
            # close() is idempotent, and this path never retries anyway.
            if outcome_1 in ("deadline", "process_exit"):
                rpc.close()
            # Snapshot BEFORE the tests run and before any retry prompt is
            # sent, so the artifact reflects what THIS attempt produced. Both
            # dumps previously happened after the block, so trajectory_1 and
            # trajectory_2 captured the same post-retry tree.
            _dump_trajectory(log_dir, "1", r1, work)
            passed, out = _score(desc, work, desc["timeout_s"])
            (log_dir / "final_output_1.txt").write_text(out)
            attempt = "pass_1" if passed else None

            if not passed and retry and outcome_1 == "completed":
                retry_prompt = (
                    "The tests failed. Output:\n\n```\n"
                    + out[-4000:]
                    + "\n```\n\nFix the implementation and try again."
                )
                r2 = rpc.prompt_and_collect(retry_prompt, timeout=ATTEMPT_TIMEOUT_S)
                outcome_2 = _attempt_outcome(r2)
                if outcome_2 in ("deadline", "process_exit"):
                    rpc.close()
                _dump_trajectory(log_dir, "2", r2, work)
                passed, out = _score(desc, work, desc["timeout_s"])
                (log_dir / "final_output_2.txt").write_text(out)
                if passed:
                    attempt = "pass_2"

        elapsed = time.time() - t0
        (log_dir / "final_output.txt").write_text(out)
        if verbose:
            print(f"[{lang}/{ex_name}] {'PASS' if passed else 'FAIL'} in {elapsed:.1f}s on {attempt or 'fail'}")

        return {
            "run_id": RUN_ID,
            "status": _classify_status(passed, attempt, outcome_1, outcome_2),
            "stop_reason_1": _stop_reason(r1),
            "stop_reason_2": _stop_reason(r2) if r2 is not None else None,
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
        "run_id": RUN_ID,
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
