"""Terminal-reason behaviour of PiRpc, driven by a fake pi subprocess.

These cover the JSONL event loop, which the existing tests cannot: they spawn a
real pi and skip when node_modules/.bin/pi is absent. EOF/deadline/crash need a
process that exits on cue.
"""
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rpc_client  # noqa: E402
from rpc_client import PiRpc  # noqa: E402

FAKE = Path(__file__).parent / "fake_pi.py"


@pytest.fixture
def fake_pi(monkeypatch):
    """Point PiRpc at the fake instead of the real pi binary."""
    monkeypatch.setattr(rpc_client, "PI_BIN", FAKE)
    monkeypatch.setattr(rpc_client, "_extension_paths", lambda: [])
    def _spawn(mode, cwd, **kw):
        monkeypatch.setenv("FAKE_PI_MODE", mode)
        return PiRpc(model="fake/model", cwd=str(cwd), **kw)
    return _spawn


def test_clean_run_reports_agent_end(fake_pi, tmp_path):
    with fake_pi("clean", tmp_path) as rpc:
        r = rpc.prompt_and_collect("go", timeout=30)
    assert r.agent_ended is True
    assert r.stop_reason == "agent_end"
    assert r.tool_calls and r.tool_calls[0]["name"] == "read"
    assert "hello" in r.assistant_text


def test_crash_after_ack_is_process_exit_not_deadline(fake_pi, tmp_path):
    """A pi that dies mid-run must not burn the whole budget or look like a timeout."""
    with fake_pi("crash_after_ack", tmp_path) as rpc:
        t0 = time.time()
        r = rpc.prompt_and_collect("go", timeout=30)
        elapsed = time.time() - t0
    assert elapsed < 10, f"took {elapsed:.1f}s -- EOF did not wake the drain"
    assert r.agent_ended is False
    assert r.stop_reason == "process_exit"


def test_hang_is_deadline(fake_pi, tmp_path):
    with fake_pi("hang_after_ack", tmp_path) as rpc:
        t0 = time.time()
        r = rpc.prompt_and_collect("go", timeout=2)
        elapsed = time.time() - t0
    assert elapsed >= 2
    assert r.agent_ended is False
    assert r.stop_reason == "deadline"


def test_agent_end_and_eof_together_still_agent_end(fake_pi, tmp_path):
    """Ordering hazard: queue must be drained before the EOF flag is consulted."""
    with fake_pi("end_then_exit", tmp_path) as rpc:
        r = rpc.prompt_and_collect("go", timeout=30)
    assert r.agent_ended is True
    assert r.stop_reason == "agent_end"


def test_exit_before_ack_raises_with_stderr(fake_pi, tmp_path):
    with fake_pi("exit_before_ack", tmp_path) as rpc:
        t0 = time.time()
        with pytest.raises(rpc_client.PiProcessExited) as exc:
            rpc.prompt_and_collect("go", timeout=30)
        elapsed = time.time() - t0
    assert elapsed < 10, f"took {elapsed:.1f}s -- did not notice the dead process"
    assert "dying before ack" in str(exc.value)


def test_stderr_is_complete_after_crash(fake_pi, tmp_path):
    """gaia/tb/harbor read stderr exactly on failure; returning fast must not race it."""
    with fake_pi("crash_after_ack", tmp_path) as rpc:
        rpc.prompt_and_collect("go", timeout=30)
        assert "boom" in rpc.stderr()


def test_prompt_after_close_raises(fake_pi, tmp_path):
    rpc = fake_pi("clean", tmp_path)
    rpc.close()
    with pytest.raises(RuntimeError):
        rpc.prompt_and_collect("go", timeout=5)


def test_close_is_idempotent(fake_pi, tmp_path):
    rpc = fake_pi("clean", tmp_path)
    rpc.close()
    rpc.close()


def test_promptresult_still_constructible_with_no_args():
    r = rpc_client.PromptResult()
    assert r.agent_ended is False
    assert r.tool_calls == []
