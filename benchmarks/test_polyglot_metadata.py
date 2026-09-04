"""Scoring parameters, resume compatibility, exit code, turn accounting."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aider_polyglot as AP  # noqa: E402

HARNESS = Path(__file__).parent / "aider_polyglot.py"


def test_params_capture_what_changes_a_score():
    d = AP.LANG_DESCRIPTORS["python"]
    p = AP._scoring_params("m/x", "python", True, d)
    for key in ("model", "language", "attempt_timeout_s", "test_timeout_s",
                "retry", "score_in_copy", "allowed_tools", "env"):
        assert key in p, key


def test_attempt_timeout_comes_from_the_env_not_argparse():
    """ATTEMPT_TIMEOUT_S is a module constant read at import; the guard must
    compare against that, not an args field that does not exist."""
    p = AP._scoring_params("m", "python", True, AP.LANG_DESCRIPTORS["python"])
    assert p["attempt_timeout_s"] == AP.ATTEMPT_TIMEOUT_S


@pytest.mark.parametrize("recorded,current,expected_count", [
    ({"a": 1}, {"a": 1}, 0),
    ({"a": 1}, {"a": 2}, 1),
    ({}, {"a": 1}, 1),                      # nothing recorded == incompatible
    ({"a": 1}, {"a": 1, "b": 2}, 1),        # a new parameter is a difference
])
def test_param_mismatches(recorded, current, expected_count):
    assert len(AP._param_mismatches(recorded, current)) == expected_count


@pytest.mark.parametrize("records,expected", [
    ({}, 0),
    ({"a": {"status": "pass_1"}}, 0),
    ({"a": {"status": "fail"}}, 0),
    ({"a": {"status": "fail_timeout"}}, 0),
    ({"a": {"status": "empty_response"}}, 0),
    ({"a": {"status": "error"}}, 1),
    ({"a": {"status": "pass_1"}, "b": {"status": "error"}}, 1),
])
def test_exit_code_only_for_harness_errors(records, expected):
    assert AP._exit_code(records) == expected


def test_exit_code_ignores_records_this_run_did_not_write():
    """A resumed run must not fail for an inherited error it never touched."""
    inherited = {"old": {"status": "error"}}
    written = {"new": {"status": "pass_1"}}
    assert AP._exit_code(written) == 0
    assert AP._exit_code({**inherited, **written}) == 1  # sanity: it does see errors


def test_missing_exercise_dir_makes_the_process_exit_nonzero(tmp_path):
    """End-to-end: a broken environment must not look like a finished 0% run."""
    env = dict(os.environ, PYTHONPATH=str(HARNESS.parent))
    r = subprocess.run(
        [sys.executable, str(HARNESS), "--language", "python",
         "--exercise", "definitely-not-an-exercise", "--model", "fake/model"],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert r.returncode != 0, f"exited 0 despite a harness error\n{r.stdout}\n{r.stderr}"
    assert "error" in (r.stdout + r.stderr).lower()


class _CountingRpc:
    """Fake agent whose attempts report distinct turn counts."""
    turns = [3, 4]

    def __init__(self, *a, **kw):
        self.cwd = Path(kw["cwd"])
        self.n = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        pass

    def prompt_and_collect(self, message, timeout=900):
        n = self.n
        self.n += 1

        class R:
            stop_reason = "agent_end"
            agent_ended = True
            turn_count = _CountingRpc.turns[n]
            compaction_events = 0
            assistant_text = "work"
            tool_calls = [{"name": "read"}]
        return R()


def test_turn_count_sums_both_attempts_on_failure(tmp_path, monkeypatch):
    """The old expression dropped r2.turn_count whenever the exercise failed,
    so a two-attempt failure under-reported its own effort."""
    src = tmp_path / "practice" / "ex"
    src.mkdir(parents=True)
    (src / "ex.py").write_text("stub")

    monkeypatch.setitem(AP.LANG_DESCRIPTORS, "faker", {
        "practice_dir": tmp_path / "practice",
        "prepare": lambda s, w: (AP._copy_exercise(s, w), ([w / "ex.py"], []))[1],
        "run_tests": lambda where, timeout: (False, "nope"),   # always fail -> retry
        "syntax_hint": "",
        "timeout_s": 5,
    })
    monkeypatch.setattr(AP, "PiRpc", _CountingRpc)
    monkeypatch.setattr(AP, "LOG_ROOT", tmp_path / "logs")

    rec = AP._run_exercise("faker", "ex", "fake/model", verbose=False, retry=True)
    assert rec["status"] == "fail"
    assert rec["turn_count"] == 7, f"expected 3+4, got {rec['turn_count']}"
