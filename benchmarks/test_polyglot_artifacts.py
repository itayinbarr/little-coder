"""Artifact hygiene: stale files must not survive a rerun, and each attempt's
snapshot must reflect that attempt.

Regression cover for a bug that produced a wrong review conclusion: LOG_ROOT is
deterministic and was never purged, so a one-attempt rerun left the PREVIOUS
run's trajectory_2/workdir_2 beside a fresh trajectory_1. Comparing that pair
looks like comparing two attempts of one run. It is not.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aider_polyglot as AP  # noqa: E402


def test_purge_removes_prior_run_artifacts(tmp_path):
    log_dir = tmp_path / "python" / "some-exercise"
    log_dir.mkdir(parents=True)
    (log_dir / "trajectory_1.json").write_text("{}")
    (log_dir / "trajectory_2.json").write_text("{}")
    (log_dir / "final_output.txt").write_text("old")
    (log_dir / "final_output_2.txt").write_text("old")
    (log_dir / "workdir_1").mkdir()
    (log_dir / "workdir_2").mkdir()
    (log_dir / "workdir_2" / "stale.py").write_text("stale")
    keep = log_dir / "notes.md"
    keep.write_text("not ours")

    AP._purge_log_dir(log_dir)

    assert not list(log_dir.glob("trajectory_*"))
    assert not list(log_dir.glob("workdir_*"))
    assert not list(log_dir.glob("final_output*"))
    assert keep.exists(), "purge must only remove harness-owned artifacts"


def test_purge_is_safe_on_empty_dir(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    AP._purge_log_dir(d)  # must not raise


def test_snapshots_of_two_attempts_differ(tmp_path):
    """The B3 regression: each attempt's workdir must capture its own state."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    work = tmp_path / "work"
    work.mkdir()

    class R:
        agent_ended = True
        turn_count = 1
        compaction_events = 0
        assistant_text = "a"
        tool_calls = []

    (work / "solution.py").write_text("attempt one")
    AP._dump_trajectory(log_dir, "1", R(), work)
    (work / "solution.py").write_text("attempt two -- different")
    AP._dump_trajectory(log_dir, "2", R(), work)

    one = (log_dir / "workdir_1" / "solution.py").read_text()
    two = (log_dir / "workdir_2" / "solution.py").read_text()
    assert one == "attempt one"
    assert two == "attempt two -- different"
    assert one != two


class _FakeRpc:
    """Stands in for PiRpc: each prompt mutates the worktree, so the ordering
    of snapshot vs prompt is observable."""

    def __init__(self, *a, **kw):
        self.cwd = Path(kw["cwd"])
        self.n = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def prompt_and_collect(self, message, timeout=900):
        self.n += 1
        (self.cwd / "solution.py").write_text(f"written by attempt {self.n}")

        class R:
            agent_ended = True
            turn_count = 1
            compaction_events = 0
            assistant_text = f"attempt {self.n}"
            tool_calls = []
        return R()


def test_attempt1_snapshot_predates_the_retry_prompt(tmp_path, monkeypatch):
    """The B3 regression, at the call site where it actually lived.

    Both _dump_trajectory calls used to sit after the `with PiRpc(...)` block,
    so attempt 1's snapshot captured the post-retry tree. Driving _run_exercise
    with a fake agent that rewrites the file on every prompt makes the ordering
    observable: if attempt 1 is snapshotted late, workdir_1 holds attempt 2's
    text.
    """
    src = tmp_path / "practice" / "ex"
    src.mkdir(parents=True)
    (src / "ex.py").write_text("stub")
    (src / "ex_test.py").write_text("test")

    def prepare(s, w):
        AP._copy_exercise(s, w)
        return [w / "ex.py"], [w / "ex_test.py"]

    monkeypatch.setitem(AP.LANG_DESCRIPTORS, "faker", {
        "practice_dir": tmp_path / "practice",
        "prepare": prepare,
        "run_tests": lambda work, timeout: (False, "boom"),   # always fail -> retry
        "syntax_hint": "",
        "timeout_s": 5,
    })
    monkeypatch.setattr(AP, "PiRpc", _FakeRpc)
    monkeypatch.setattr(AP, "LOG_ROOT", tmp_path / "logs")

    AP._run_exercise("faker", "ex", "fake/model", verbose=False, retry=True)

    log_dir = tmp_path / "logs" / "faker" / "ex"
    one = (log_dir / "workdir_1" / "solution.py").read_text()
    two = (log_dir / "workdir_2" / "solution.py").read_text()
    assert one == "written by attempt 1", f"attempt 1 snapshot is stale: {one!r}"
    assert two == "written by attempt 2"
    assert (log_dir / "final_output_1.txt").exists()
    assert (log_dir / "final_output_2.txt").exists()


def test_run_id_is_stable_within_a_process():
    assert AP.RUN_ID and AP.RUN_ID == AP.RUN_ID
