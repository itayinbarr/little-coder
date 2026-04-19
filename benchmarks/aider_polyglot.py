#!/usr/bin/env python3
"""Run the full Aider Polyglot benchmark (6 languages, 225 exercises) through
little-coder, or a single language subset.

For each exercise:
  1. Copy the exercise to a temp directory named after the exercise.
  2. Apply language-specific transforms so ALL tests actually run:
        - rust: use `cargo test -- --include-ignored`
        - js:   strip xit/xtest/xdescribe skip markers in *.spec.js
        - java: strip @Disabled annotations from src/test/java/**.java
        - cpp:  build with -DEXERCISM_RUN_ALL_TESTS, use vendored Catch2
     These transforms were discovered during smoke testing — without them,
     Exercism's "student progresses through tests" design silently gates all
     but the first test, and a passing stub scores green incorrectly.
  3. Give the agent the stub file(s) + test file(s) and ask it to implement.
  4. Run the language-native test runner.
  5. If it fails, give the agent the error output for a second attempt.
  6. Record pass/fail + timing to results_full_polyglot.json (atomic flush)
     and a per-exercise log under benchmarks/full_polyglot_logs/<lang>/.

The harness is resumable: `--resume` loads the existing results file and
skips any exercise already recorded as pass_1/pass_2/fail.

Usage:
    python benchmarks/aider_polyglot.py [model] [--language <name>|all]
                                        [--exercise <name>] [--exercises N]
                                        [--resume] [--no-retry] [--verbose]

Languages: python, go, rust, cpp, javascript, java, all (default: all)
"""
import sys
import os
import time
import shutil
import json
import re
import subprocess
import argparse
import tempfile
import datetime
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent
from context import build_system_prompt
from config import load_config
from workspace import detect_language as _detect_language_general

BENCHMARK_ROOT = Path.home() / "Documents" / "polyglot-benchmark"
REPO_ROOT      = Path(__file__).parent.parent
RESULTS_FILE   = Path(__file__).parent / "results_full_polyglot.json"
LOG_ROOT       = Path(__file__).parent / "full_polyglot_logs"


# ---------------------------------------------------------------------------
# Per-language descriptors
# ---------------------------------------------------------------------------
#
# Each language descriptor is a dict with:
#   practice_dir  : Path to the exercises/practice directory
#   prepare       : (src_dir, work_dir) -> (stub_abs_paths, test_abs_paths)
#                   Copies exercise into work_dir, applies transforms,
#                   returns the paths the agent should see.
#   run_tests     : (work_dir, timeout) -> (passed: bool, output: str)
#                   Runs the native test runner in work_dir.
#   syntax_hint   : str injected into the agent prompt
#   timeout_s     : per-exercise test-runner timeout
#
# The core loop is language-agnostic and drives these via the dict.


def _rmtree(p: Path):
    shutil.rmtree(p, ignore_errors=True)


def _copy_exercise(src_dir: Path, work_dir: Path):
    """Copy exercise directory tree to work_dir, EXCLUDING .meta/.

    Every Aider Polyglot exercise ships a reference solution in .meta/
    (.meta/example.{py,go,rs,cpp,h}, .meta/proof.ci.js, or
    .meta/src/reference/java/<Name>.java). The agent must not see this
    directory — Reading it would be silent cheating and invalidate the
    measurement. .docs/ is deliberately kept: it's the student-facing
    problem description, which is legitimate input.

    cpp NEEDS the work_dir to be named after the exercise (CMakeLists
    derives source names from dir name). The caller is responsible for
    constructing work_dir with the right name.
    """
    if work_dir.exists():
        _rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    for item in src_dir.iterdir():
        if item.name == ".meta":
            continue  # reference solution lives here — do not leak it
        dest = work_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)


# ----- python ---------------------------------------------------------------

def _prepare_python(src: Path, work: Path):
    _copy_exercise(src, work)
    stubs = sorted(
        str(p) for p in work.iterdir()
        if p.is_file() and p.suffix == ".py"
        and "_test" not in p.name and p.name != "__init__.py"
    )
    tests = sorted(str(p) for p in work.iterdir() if p.is_file() and p.name.endswith("_test.py"))
    return stubs, tests


def _run_python(work: Path, timeout: int):
    tests = list(work.glob("*_test.py"))
    if not tests:
        return False, "No test file found"
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", str(tests[0]), "-v", "--tb=short", "-q"],
            cwd=work, capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, f"Tests timed out ({timeout}s)"


# ----- go -------------------------------------------------------------------

def _prepare_go(src: Path, work: Path):
    _copy_exercise(src, work)
    stubs = sorted(
        str(p) for p in work.iterdir()
        if p.is_file() and p.suffix == ".go" and not p.name.endswith("_test.go")
        and p.name != "go.mod"
    )
    tests = sorted(str(p) for p in work.iterdir() if p.name.endswith("_test.go"))
    return stubs, tests


def _run_go(work: Path, timeout: int):
    try:
        r = subprocess.run(
            ["go", "test", "./..."],
            cwd=work, capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, f"Tests timed out ({timeout}s)"
    except FileNotFoundError:
        return False, "go toolchain not installed"


# ----- rust -----------------------------------------------------------------

def _prepare_rust(src: Path, work: Path):
    _copy_exercise(src, work)
    # Stub is src/lib.rs; test is tests/<name>.rs
    stubs = [str(work / "src" / "lib.rs")] if (work / "src" / "lib.rs").exists() else []
    tests = sorted(str(p) for p in (work / "tests").glob("*.rs")) if (work / "tests").exists() else []
    return stubs, tests


def _run_rust(work: Path, timeout: int):
    """`cargo test -- --include-ignored` so Exercism's #[ignore] advanced
    tests actually run. Without --include-ignored, a stub that passes only
    the first unignored test scores green incorrectly.
    """
    env = os.environ.copy()
    env["PATH"] = f"{os.path.expanduser('~/.cargo/bin')}:{env.get('PATH', '')}"
    try:
        r = subprocess.run(
            ["cargo", "test", "--", "--include-ignored"],
            cwd=work, capture_output=True, text=True, timeout=timeout, env=env,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, f"Tests timed out ({timeout}s)"
    except FileNotFoundError:
        return False, "cargo not installed"


# ----- javascript -----------------------------------------------------------

_JS_SKIP_MARKER_RE = re.compile(r"\b(xit|xtest|xdescribe)\s*\(")


def _prepare_javascript(src: Path, work: Path):
    _copy_exercise(src, work)
    # Strip Exercism skip markers from every *.spec.js so all tests run.
    for spec in work.glob("*.spec.js"):
        txt = spec.read_text()
        new = _JS_SKIP_MARKER_RE.sub(
            lambda m: {"xit": "it(", "xtest": "test(", "xdescribe": "describe("}[m.group(1)],
            txt,
        )
        if new != txt:
            spec.write_text(new)
    stubs = sorted(
        str(p) for p in work.iterdir()
        if p.is_file() and p.suffix == ".js"
        and not p.name.endswith(".spec.js")
        and p.name not in ("babel.config.js",)
    )
    tests = sorted(str(p) for p in work.iterdir() if p.name.endswith(".spec.js"))
    return stubs, tests


def _run_javascript(work: Path, timeout: int):
    # npm install (silent) before every run — per-exercise node_modules.
    try:
        subprocess.run(
            ["npm", "install", "--silent", "--no-audit", "--no-fund"],
            cwd=work, capture_output=True, text=True, timeout=max(120, timeout),
        )
    except Exception as e:
        return False, f"npm install failed: {e}"
    try:
        r = subprocess.run(
            ["npm", "test", "--silent"],
            cwd=work, capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, f"Tests timed out ({timeout}s)"


# ----- java -----------------------------------------------------------------

_JAVA_DISABLED_RE = re.compile(r"^[ \t]*@Disabled\b.*$", re.MULTILINE)


def _prepare_java(src: Path, work: Path):
    _copy_exercise(src, work)
    # Strip @Disabled annotations so gradle actually runs every @Test method.
    test_root = work / "src" / "test" / "java"
    if test_root.exists():
        for jf in test_root.rglob("*.java"):
            txt = jf.read_text()
            new = _JAVA_DISABLED_RE.sub("", txt)
            if new != txt:
                jf.write_text(new)
    gradlew = work / "gradlew"
    if gradlew.exists():
        gradlew.chmod(0o755)
    # Stub is src/main/java/<ClassName>.java
    main_java = work / "src" / "main" / "java"
    stubs = sorted(str(p) for p in main_java.rglob("*.java")) if main_java.exists() else []
    tests = sorted(str(p) for p in test_root.rglob("*.java")) if test_root.exists() else []
    return stubs, tests


def _run_java(work: Path, timeout: int):
    gradlew = work / "gradlew"
    if not gradlew.exists():
        return False, "gradlew not found"
    try:
        r = subprocess.run(
            [str(gradlew), "test", "--no-daemon", "-q"],
            cwd=work, capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, f"Tests timed out ({timeout}s)"


# ----- cpp ------------------------------------------------------------------

def _prepare_cpp(src: Path, work: Path):
    # work_dir MUST be named after the exercise — caller ensures this.
    _copy_exercise(src, work)
    stubs = sorted(
        str(p) for p in work.iterdir()
        if p.is_file() and p.suffix in (".cpp", ".h")
        and not p.name.endswith("_test.cpp")
    )
    tests = sorted(str(p) for p in work.iterdir() if p.name.endswith("_test.cpp"))
    return stubs, tests


def _run_cpp(work: Path, timeout: int):
    """Build with -DEXERCISM_RUN_ALL_TESTS so all Catch2 cases run.
    Do NOT define EXERCISM_TEST_SUITE — that branch uses catch2/catch.hpp
    (v2 single-header), which doesn't exist in Ubuntu's catch2 v3. The
    default branch uses the vendored test/catch.hpp bundled per exercise.
    The CMakeLists declares a `test_<name>` custom target that runs the
    compiled test binary during build, so `cmake --build` exit code is
    authoritative — ctest is not wired up by the polyglot benchmark layout.
    """
    build_dir = work / "build"
    try:
        cfg = subprocess.run(
            ["cmake", "-S", str(work), "-B", str(build_dir),
             "-DCMAKE_CXX_FLAGS=-DEXERCISM_RUN_ALL_TESTS"],
            capture_output=True, text=True, timeout=timeout,
        )
        if cfg.returncode != 0:
            return False, "cmake config failed:\n" + cfg.stdout + cfg.stderr
        build = subprocess.run(
            ["cmake", "--build", str(build_dir)],
            capture_output=True, text=True, timeout=timeout,
        )
        return build.returncode == 0, (build.stdout + build.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, f"Build/test timed out ({timeout}s)"


# ---------------------------------------------------------------------------

# Language descriptors — test-correctness infrastructure only.
#
# Deliberately NO per-language prompt guidance here. Any language or
# tool-use hints must come from little-coder's own skill + knowledge
# systems (skill/tools/, skill/knowledge/), not from the benchmark,
# so the benchmark measures little-coder as a real user would use it.
#
# What lives in each descriptor is strictly test-correctness: how to
# discover stubs and tests in this language's directory layout, how
# to apply the skip-marker transforms that prevent silent cheating,
# and how to invoke the language's native test runner.

LANGUAGES = {
    "python": {
        "practice_dir": BENCHMARK_ROOT / "python" / "exercises" / "practice",
        "prepare": _prepare_python,
        "run_tests": _run_python,
        "timeout_s": 60,
    },
    "go": {
        "practice_dir": BENCHMARK_ROOT / "go" / "exercises" / "practice",
        "prepare": _prepare_go,
        "run_tests": _run_go,
        "timeout_s": 60,
    },
    "rust": {
        "practice_dir": BENCHMARK_ROOT / "rust" / "exercises" / "practice",
        "prepare": _prepare_rust,
        "run_tests": _run_rust,
        "timeout_s": 180,
    },
    "javascript": {
        "practice_dir": BENCHMARK_ROOT / "javascript" / "exercises" / "practice",
        "prepare": _prepare_javascript,
        "run_tests": _run_javascript,
        "timeout_s": 90,
    },
    "java": {
        "practice_dir": BENCHMARK_ROOT / "java" / "exercises" / "practice",
        "prepare": _prepare_java,
        "run_tests": _run_java,
        "timeout_s": 300,
    },
    "cpp": {
        "practice_dir": BENCHMARK_ROOT / "cpp" / "exercises" / "practice",
        "prepare": _prepare_cpp,
        "run_tests": _run_cpp,
        "timeout_s": 240,
    },
}


LANGUAGE_ORDER = ["python", "go", "rust", "javascript", "cpp", "java"]


# ---------------------------------------------------------------------------
# Language detection (delegated to workspace.py)
# ---------------------------------------------------------------------------
#
# The fingerprinting logic lives in workspace.py at the repo root so it is
# available to any little-coder component, not just this benchmark. The
# harness uses it as a sanity check that a --language flag actually matches
# the exercise layout on disk.

def detect_language(exercise_dir: Path) -> Optional[str]:
    """Language name for an exercise directory, or None if unknown.
    Thin wrapper around workspace.detect_language.
    """
    return _detect_language_general(exercise_dir)


def resolve_exercise(exercise_dir: Path) -> Optional[tuple]:
    """Given an arbitrary exercise directory, return (lang_name, descriptor)
    ready for the core loop to drive. Returns None if the language can't
    be detected or isn't registered in LANGUAGES.
    """
    lang = detect_language(exercise_dir)
    if lang is None or lang not in LANGUAGES:
        return None
    return lang, LANGUAGES[lang]


# ---------------------------------------------------------------------------
# Agent runner (language-agnostic core loop)
# ---------------------------------------------------------------------------

def _build_first_prompt(exercise_name: str, stubs: list, work_dir: Path) -> str:
    """Minimal natural-user prompt.

    Deliberately does NOT inject docs, test content, syntax hints, or
    tool-use guidance. The agent is told *where* to look (working
    directory + stub path), not *what* the problem is or *how* to
    approach it. Workspace awareness, docs discovery, and tool-use
    patterns must come from little-coder's skill + knowledge systems
    (auto-injected on keyword match and tool-use history), not from
    the benchmark harness.
    """
    if stubs:
        stub_line = f"The stub file you need to implement is at {stubs[0]}."
    else:
        stub_line = ""
    return (
        f"Please implement the '{exercise_name}' exercise. "
        f"The working directory is {work_dir}. "
        f"{stub_line} "
        f"Explore the directory if you need more context, then implement "
        f"the solution and run the tests to verify."
    ).strip()


def _build_retry_prompt(exercise_name: str, stubs: list, test_output: str) -> str:
    """Minimal retry prompt — feeds the test failure back and asks for a fix."""
    stub_line = f"The stub file is at {stubs[0]}." if stubs else ""
    return (
        f"The tests for '{exercise_name}' failed. Here is the test output:\n\n"
        f"```\n{test_output[:2000]}\n```\n\n"
        f"{stub_line} Please fix the implementation so the tests pass."
    ).strip()


def _run_agent(prompt: str, cfg: dict, system: str, work_dir: Path,
               max_turns: int, log_fh, verbose: bool) -> dict:
    """Drive agent.run() and return a stats dict for results tracking.

    Returns:
        {
          "text": str,              # model text output
          "tools": list[str],       # tool names in call order
          "write_refusals": int,    # count of Write calls refused by the guard
          "turns": int,             # state.turn_count at end
          "error": str | None,      # agent exception message if one fired
        }
    """
    cfg["_working_dir"] = str(work_dir)
    state = agent.AgentState()
    text_out = ""
    tools: list[str] = []
    write_refusals = 0
    error = None
    try:
        for e in agent.run(prompt, state, cfg, system):
            if isinstance(e, agent.TextChunk):
                text_out += e.text
                log_fh.write(e.text)
                if verbose:
                    print(e.text, end="", flush=True)
            elif isinstance(e, agent.ToolStart):
                tools.append(e.name)
                msg = f"\n  >> TOOL: {e.name}({e.inputs})\n"
                log_fh.write(msg)
                if verbose:
                    print(msg, end="")
            elif isinstance(e, agent.ToolEnd):
                if e.name == "Write" and isinstance(e.result, str) and e.result.startswith("Error: Write refused"):
                    write_refusals += 1
                preview = (e.result[:500] if e.result else "(empty)")
                msg = f"  << RESULT ({e.name}): {preview}\n"
                log_fh.write(msg)
                if verbose:
                    print(msg, end="")
            if state.turn_count >= max_turns:
                break
    except Exception as ex:
        error = str(ex)
        text_out += f"\nAGENT ERROR: {ex}"
        log_fh.write(f"\nAGENT ERROR: {ex}\n")
    log_fh.flush()
    return {
        "text": text_out,
        "tools": tools,
        "write_refusals": write_refusals,
        "turns": state.turn_count,
        "error": error,
    }


# ---------------------------------------------------------------------------
# Results file (atomic, resumable)
# ---------------------------------------------------------------------------

def _empty_results(model: str) -> dict:
    now = datetime.datetime.now().isoformat(timespec="seconds")
    langs = {}
    for name in LANGUAGE_ORDER:
        practice = LANGUAGES[name]["practice_dir"]
        if not practice.exists():
            total = 0
        else:
            total = sum(1 for p in practice.iterdir() if p.is_dir())
        langs[name] = {
            "total": total, "done": 0,
            "pass_1": 0, "pass_2": 0, "fail": 0,
            "details": [],  # [{name, status, time, tools, write_refusals, turns, first_error}]
        }
    return {
        "model": model,
        "started_at": now,
        "updated_at": now,
        "current": None,   # {lang, name, started_at, attempt} while an exercise is in flight
        "languages": langs,
        "overall": {"total": sum(l["total"] for l in langs.values()),
                    "done": 0, "passed": 0, "pct": 0.0},
    }


def _recompute_overall(results: dict):
    total = 0; done = 0; passed = 0
    for l in results["languages"].values():
        total += l["total"]
        done += l["done"]
        passed += l["pass_1"] + l["pass_2"]
    results["overall"] = {
        "total": total, "done": done, "passed": passed,
        "pct": round(100 * passed / total, 2) if total else 0.0,
    }


def _flush_results(results: dict):
    results["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    _recompute_overall(results)
    tmp = RESULTS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(results, indent=2))
    os.replace(tmp, RESULTS_FILE)


def _load_or_init_results(model: str, resume: bool) -> dict:
    if resume and RESULTS_FILE.exists():
        try:
            data = json.loads(RESULTS_FILE.read_text())
            if data.get("model") != model:
                print(f"WARNING: resume file model={data.get('model')} != current model={model}")
            # Ensure every language entry exists (in case polyglot tracks change)
            base = _empty_results(model)
            for name in LANGUAGE_ORDER:
                if name not in data.get("languages", {}):
                    data.setdefault("languages", {})[name] = base["languages"][name]
            return data
        except Exception as e:
            print(f"Could not read existing results ({e}) — starting fresh")
    return _empty_results(model)


def _already_done(results: dict, lang: str, exercise: str) -> Optional[str]:
    for d in results["languages"][lang]["details"]:
        if d["name"] == exercise:
            return d["status"]
    return None


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

def _first_error_line(test_output: str) -> str:
    """Extract the most informative first-error line from pytest/test output."""
    for line in test_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if (stripped.startswith("FAIL") or stripped.startswith("E ") or
                stripped.startswith("E\t") or "Error:" in stripped or
                stripped.startswith("--- FAIL") or "AssertionError" in stripped):
            return stripped[:160]
    return ""


def _tool_counter(tools: list) -> dict:
    counts: dict = {}
    for t in tools:
        counts[t] = counts.get(t, 0) + 1
    return counts


def run_exercise(lang_name: str, exercise_name: str, cfg: dict, system: str,
                 results: dict, no_retry: bool, verbose: bool) -> None:
    lang = LANGUAGES[lang_name]
    src = lang["practice_dir"] / exercise_name
    if not src.is_dir():
        return

    log_dir = LOG_ROOT / lang_name
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{exercise_name}.log"
    log_fh = log_path.open("w")

    # Mark this exercise as in-flight so polyglot_status can report it
    # without reading the log file.
    results["current"] = {
        "lang": lang_name,
        "name": exercise_name,
        "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "attempt": 1,
    }
    _flush_results(results)

    # Work dir MUST be named after the exercise (cpp CMakeLists requires it).
    work_parent = Path(tempfile.mkdtemp(prefix=f"polyglot_{lang_name}_"))
    work = work_parent / exercise_name
    try:
        stubs, tests = lang["prepare"](src, work)
        log_fh.write(f"=== {lang_name}/{exercise_name} ===\n")
        log_fh.write(f"stubs: {stubs}\ntests: {tests}\n\n")

        if not stubs or not tests:
            msg = f"  SKIP (no stubs or no tests discovered)"
            print(msg, flush=True)
            log_fh.write(msg + "\n")
            return

        t0 = time.time()

        # First attempt
        prompt = _build_first_prompt(exercise_name, stubs, work)
        agent_stats1 = _run_agent(prompt, cfg, system, work, max_turns=12, log_fh=log_fh, verbose=verbose)
        passed, test_out = lang["run_tests"](work, lang["timeout_s"])
        log_fh.write(f"\n--- TEST OUTPUT (attempt 1) ---\n{test_out}\n")
        elapsed = time.time() - t0

        # Aggregate fields that are identical for pass or fail paths
        all_tools = list(agent_stats1["tools"])
        total_refusals = agent_stats1["write_refusals"]
        total_turns = agent_stats1["turns"]

        entry = {
            "name": exercise_name,
            "status": None,
            "time": round(elapsed, 1),
            "tools": {},
            "write_refusals": 0,
            "turns": 0,
            "first_error": "",
        }
        lentry = results["languages"][lang_name]

        if passed:
            lentry["pass_1"] += 1
            entry["status"] = "pass_1"
            print(f"  ✓ PASS (1st, {elapsed:.1f}s)", flush=True)
        elif no_retry:
            lentry["fail"] += 1
            entry["status"] = "fail"
            entry["first_error"] = _first_error_line(test_out)
            print(f"  ✗ FAIL ({elapsed:.1f}s)", flush=True)
        else:
            print(f"  ... retrying", end="", flush=True)
            # mark that we're into the retry attempt
            if results.get("current"):
                results["current"]["attempt"] = 2
                _flush_results(results)
            retry_prompt = _build_retry_prompt(exercise_name, stubs, test_out)
            agent_stats2 = _run_agent(retry_prompt, cfg, system, work, max_turns=8, log_fh=log_fh, verbose=verbose)
            passed2, test_out2 = lang["run_tests"](work, lang["timeout_s"])
            log_fh.write(f"\n--- TEST OUTPUT (attempt 2) ---\n{test_out2}\n")
            elapsed = time.time() - t0
            entry["time"] = round(elapsed, 1)
            all_tools.extend(agent_stats2["tools"])
            total_refusals += agent_stats2["write_refusals"]
            total_turns += agent_stats2["turns"]
            if passed2:
                lentry["pass_2"] += 1
                entry["status"] = "pass_2"
                print(f"\r  ✓ PASS (2nd, {elapsed:.1f}s)      ", flush=True)
            else:
                lentry["fail"] += 1
                entry["status"] = "fail"
                entry["first_error"] = _first_error_line(test_out2)
                print(f"\r  ✗ FAIL ({elapsed:.1f}s)            ", flush=True)
                if entry["first_error"]:
                    print(f"    {entry['first_error'][:100]}", flush=True)

        entry["tools"] = _tool_counter(all_tools)
        entry["write_refusals"] = total_refusals
        entry["turns"] = total_turns
        lentry["done"] += 1
        lentry["details"].append(entry)
        results["current"] = None
        _flush_results(results)
    finally:
        log_fh.close()
        _rmtree(work_parent)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model", nargs="?", default="ollama/qwen3.5")
    parser.add_argument("--language", default="all",
                        help="Single language name or 'all' (default: all)")
    parser.add_argument("--exercises", type=int, default=0,
                        help="Limit number of exercises per language (0=all)")
    parser.add_argument("--exercise", type=str, default="",
                        help="Run a single exercise by name (use with --language)")
    parser.add_argument("--no-retry", action="store_true")
    parser.add_argument("--resume", action="store_true",
                        help="Skip exercises already recorded in results file")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not BENCHMARK_ROOT.exists():
        print(f"ERROR: polyglot-benchmark not found at {BENCHMARK_ROOT}")
        print("Clone: git clone https://github.com/Aider-AI/polyglot-benchmark.git ~/Documents/polyglot-benchmark")
        return 1

    if args.language == "all":
        langs_to_run = list(LANGUAGE_ORDER)
    elif args.language in LANGUAGES:
        langs_to_run = [args.language]
    else:
        print(f"ERROR: unknown language '{args.language}'. Choose from {LANGUAGE_ORDER} or 'all'.")
        return 1

    # Sanity-check any language we're about to run actually has its
    # practice dir present (polyglot-benchmark must be cloned).
    for ln in langs_to_run:
        pd = LANGUAGES[ln]["practice_dir"]
        if not pd.exists():
            print(f"ERROR: {ln} practice dir not found at {pd}")
            return 1

    cfg = load_config()
    cfg["model"] = args.model
    cfg["permission_mode"] = "accept-all"
    system = build_system_prompt(cfg)

    from local.config import is_small_model, get_model_profile
    small = is_small_model(args.model)
    profile = get_model_profile(args.model) if small else {}

    results = _load_or_init_results(args.model, args.resume)
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    _flush_results(results)

    print(f"\n{'='*72}")
    print(f"  Aider Polyglot Benchmark — little-coder")
    print(f"  Model: {args.model}  Small-model optimizations: {'ON' if small else 'OFF'}")
    if small:
        print(f"  Context: {profile.get('context_limit')}  Skills: {profile.get('skill_token_budget')}tok")
    print(f"  Languages: {langs_to_run}  Resume: {args.resume}  Retry: {not args.no_retry}")
    total_exercises = sum(results["languages"][ln]["total"] for ln in langs_to_run)
    print(f"  Exercises to run: {total_exercises}  (Results: {RESULTS_FILE})")
    print(f"{'='*72}\n")

    for lang_name in langs_to_run:
        exercises = sorted(p.name for p in LANGUAGES[lang_name]["practice_dir"].iterdir() if p.is_dir())
        if args.exercise:
            exercises = [e for e in exercises if e == args.exercise]
            if not exercises:
                continue
        elif args.exercises > 0:
            exercises = exercises[:args.exercises]

        print(f"\n--- {lang_name} ({len(exercises)} exercises) ---")
        for i, ex in enumerate(exercises):
            prior = _already_done(results, lang_name, ex) if args.resume else None
            if prior:
                print(f"[{i+1}/{len(exercises)}] {lang_name}/{ex}  (cached: {prior})")
                continue
            # Sanity-check: the exercise directory should fingerprint as the
            # language we think we're running. This catches benchmark-layout
            # drift before we waste agent turns on it.
            src = LANGUAGES[lang_name]["practice_dir"] / ex
            detected = detect_language(src)
            if detected != lang_name:
                print(f"[{i+1}/{len(exercises)}] {lang_name}/{ex}  SKIP "
                      f"(fingerprint mismatch: detected={detected})")
                continue
            print(f"[{i+1}/{len(exercises)}] {lang_name}/{ex}", flush=True)
            run_exercise(lang_name, ex, cfg, system, results, args.no_retry, args.verbose)

    # Final summary
    print(f"\n{'='*72}")
    print(f"  RESULTS")
    print(f"{'='*72}")
    for ln in LANGUAGE_ORDER:
        l = results["languages"][ln]
        if l["done"] == 0:
            continue
        pct = 100 * (l["pass_1"] + l["pass_2"]) / l["done"]
        print(f"  {ln:<11} {l['pass_1'] + l['pass_2']:>3}/{l['done']:<3} "
              f"(1st: {l['pass_1']}, 2nd: {l['pass_2']}, fail: {l['fail']})  {pct:5.1f}%")
    overall = results["overall"]
    print(f"  {'-'*60}")
    print(f"  {'OVERALL':<11} {overall['passed']:>3}/{overall['done']:<3}  {overall['pct']:5.2f}%")
    print(f"\n  Results file: {RESULTS_FILE}")
    print(f"  Logs dir:     {LOG_ROOT}")
    print(f"{'='*72}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
