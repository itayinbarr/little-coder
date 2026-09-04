"""Precedence rules for the recorded status, and score-in-a-copy isolation.

Pure functions, table-tested: this is where a wrong precedence silently turns a
pass into an error, or hides a provider fault as a model failure.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aider_polyglot as AP  # noqa: E402


class Res:
    def __init__(self, stop_reason=None, agent_ended=True, turn_count=3,
                 tool_calls=None, assistant_text="did work"):
        if stop_reason is not None:
            self.stop_reason = stop_reason
        self.agent_ended = agent_ended
        self.turn_count = turn_count
        self.tool_calls = tool_calls if tool_calls is not None else [{"name": "read"}]
        self.assistant_text = assistant_text


# ── _stop_reason shim ────────────────────────────────────────────────────
def test_stop_reason_prefers_the_real_field():
    assert AP._stop_reason(Res(stop_reason="process_exit")) == "process_exit"


def test_stop_reason_degrades_when_field_absent():
    """rpc_client without stop_reason (or reverted) must not break scoring."""
    assert AP._stop_reason(Res(agent_ended=True)) == "agent_end"
    assert AP._stop_reason(Res(agent_ended=False)) == "deadline"


# ── empty responses ──────────────────────────────────────────────────────
@pytest.mark.parametrize("res,expected", [
    (Res(stop_reason="agent_end", turn_count=1, tool_calls=[], assistant_text=""), True),
    (Res(stop_reason="agent_end", turn_count=1, tool_calls=[], assistant_text="   "), True),
    (Res(stop_reason="agent_end", turn_count=1, tool_calls=[{"name": "read"}], assistant_text=""), False),
    (Res(stop_reason="agent_end", turn_count=4, tool_calls=[], assistant_text="text"), False),
    (Res(stop_reason="deadline", agent_ended=False, turn_count=0, tool_calls=[], assistant_text=""), False),
])
def test_is_empty_response(res, expected):
    assert AP._is_empty_response(res) is expected


# ── _attempt_outcome wires the pieces together ───────────────────────────
@pytest.mark.parametrize("res,expected", [
    (Res(stop_reason="process_exit"), "process_exit"),
    (Res(stop_reason="deadline"), "deadline"),
    (Res(stop_reason="agent_end"), "completed"),
    # the branch a mutation test caught as untested: an agent_end with no work
    # must become empty_response, not completed
    (Res(stop_reason="agent_end", turn_count=1, tool_calls=[], assistant_text=""),
     "empty_response"),
    # process_exit outranks emptiness -- the process dying is the bigger fact
    (Res(stop_reason="process_exit", turn_count=1, tool_calls=[], assistant_text=""),
     "process_exit"),
])
def test_attempt_outcome(res, expected):
    assert AP._attempt_outcome(res) == expected


# ── precedence table ─────────────────────────────────────────────────────
@pytest.mark.parametrize("passed,attempt,o1,o2,expected", [
    # passing beats everything, including a process that then died
    (True,  "pass_1", "completed",      None,            "pass_1"),
    (True,  "pass_1", "process_exit",   None,            "pass_1"),
    (True,  "pass_2", "completed",      "process_exit",  "pass_2"),
    # single attempt
    (False, None,     "process_exit",   None,            "error"),
    (False, None,     "deadline",       None,            "fail_timeout"),
    (False, None,     "empty_response", None,            "empty_response"),
    (False, None,     "completed",      None,            "fail"),
    # retry ran: attempt 1 was scored, so a dead pi is a failed exercise
    (False, None,     "completed",      "process_exit",  "fail"),
    (False, None,     "completed",      "deadline",      "fail_timeout"),
    (False, None,     "completed",      "empty_response","empty_response"),
    (False, None,     "completed",      "completed",     "fail"),
])
def test_classify_status(passed, attempt, o1, o2, expected):
    assert AP._classify_status(passed, attempt, o1, o2) == expected


def test_a_pass_is_never_downgraded_to_error():
    """Regression guard: applying process_exit before checking `passed` would
    turn a pi that exited right after writing a correct solution into an error."""
    assert AP._classify_status(True, "pass_1", "process_exit", None) == "pass_1"


# ── score in a copy ──────────────────────────────────────────────────────
def test_score_in_copy_does_not_run_in_the_agents_tree(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "solution.py").write_text("x = 1")
    seen = {}

    def run_tests(where, timeout):
        seen["where"] = Path(where)
        (Path(where) / "test_droppings").write_text("pytest was here")
        return True, "ok"

    desc = {"score_in_copy": True, "run_tests": run_tests, "timeout_s": 5}
    passed, out = AP._score(desc, work, 5)

    assert passed and out == "ok"
    assert seen["where"] != work, "tests ran in the agent's own tree"
    assert (work / "solution.py").exists()
    assert not (work / "test_droppings").exists(), "scoring polluted the agent's tree"


def test_score_without_flag_uses_the_tree_directly(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    seen = {}
    desc = {"run_tests": lambda where, t: (seen.setdefault("where", Path(where)), (True, "ok"))[1],
            "timeout_s": 5}
    AP._score(desc, work, 5)
    assert seen["where"] == work


def test_python_descriptor_scores_in_a_copy():
    assert AP.LANG_DESCRIPTORS["python"].get("score_in_copy") is True
