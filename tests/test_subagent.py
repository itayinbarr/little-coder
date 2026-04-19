"""Tests for the sub-agent system (subagent.py)."""
import time
import threading

import pytest

from multi_agent.subagent import SubAgentManager, SubAgentTask, _extract_final_text


# ── Mock for _agent_run ──────────────────────────────────────────────────

def _make_mock_agent_run(sleep_per_iter=0.05, iters=3):
    """Return a mock _agent_run that simulates work and checks cancellation."""

    def mock_agent_run(prompt, state, config, system_prompt, depth=0, cancel_check=None):
        for i in range(iters):
            if cancel_check and cancel_check():
                return
            time.sleep(sleep_per_iter)
        # Append an assistant message to state
        state.messages.append({
            "role": "assistant",
            "content": f"Result for: {prompt}",
            "tool_calls": [],
        })
        # Yield a TurnDone-like event (generator protocol)
        yield None

    return mock_agent_run


def _make_slow_mock(sleep_per_iter=0.2, iters=10):
    """Return a slow mock for cancellation testing."""
    return _make_mock_agent_run(sleep_per_iter=sleep_per_iter, iters=iters)


@pytest.fixture
def manager(monkeypatch):
    """Create a SubAgentManager with mocked _agent_run."""
    mock = _make_mock_agent_run()
    monkeypatch.setattr("multi_agent.subagent._agent_run", mock)
    mgr = SubAgentManager(max_concurrent=3, max_depth=3)
    yield mgr
    mgr.shutdown()


@pytest.fixture
def slow_manager(monkeypatch):
    """Create a SubAgentManager with a slow mock for cancel testing."""
    mock = _make_slow_mock()
    monkeypatch.setattr("multi_agent.subagent._agent_run", mock)
    mgr = SubAgentManager(max_concurrent=3, max_depth=3)
    yield mgr
    mgr.shutdown()


# ── Tests ────────────────────────────────────────────────────────────────

class TestSpawnAndWait:
    def test_spawn_and_wait_completes(self, manager):
        task = manager.spawn("hello", {}, "system")
        result_task = manager.wait(task.id, timeout=5)
        assert result_task is not None
        assert result_task.status == "completed"
        assert result_task.result == "Result for: hello"

    def test_spawn_returns_immediately(self, manager):
        task = manager.spawn("hello", {}, "system")
        # Task should be pending or running, not yet completed
        assert task.status in ("pending", "running")


class TestListTasks:
    def test_list_tasks(self, manager):
        t1 = manager.spawn("task1", {}, "system")
        t2 = manager.spawn("task2", {}, "system")
        tasks = manager.list_tasks()
        task_ids = [t.id for t in tasks]
        assert t1.id in task_ids
        assert t2.id in task_ids
        assert len(tasks) == 2


class TestCancel:
    def test_cancel_running_task(self, slow_manager):
        task = slow_manager.spawn("slow task", {}, "system")
        # Wait briefly to ensure the task starts running
        time.sleep(0.1)
        assert task.status == "running"
        success = slow_manager.cancel(task.id)
        assert success is True
        # Wait for the task to actually finish
        slow_manager.wait(task.id, timeout=5)
        assert task.status == "cancelled"


class TestDepthLimit:
    def test_spawn_at_max_depth_fails(self, manager):
        task = manager.spawn("deep", {}, "system", depth=3)
        assert task.status == "failed"
        assert "Max depth" in task.result


class TestGetResult:
    def test_get_result_completed(self, manager):
        task = manager.spawn("hello", {}, "system")
        manager.wait(task.id, timeout=5)
        result = manager.get_result(task.id)
        assert result == "Result for: hello"

    def test_get_result_unknown_id(self, manager):
        result = manager.get_result("nonexistent_id")
        assert result is None


class TestExtractFinalText:
    def test_extracts_last_assistant(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "first"},
            {"role": "user", "content": "more"},
            {"role": "assistant", "content": "second"},
        ]
        assert _extract_final_text(messages) == "second"

    def test_returns_none_for_empty(self):
        assert _extract_final_text([]) is None

    def test_returns_none_no_assistant(self):
        messages = [{"role": "user", "content": "hi"}]
        assert _extract_final_text(messages) is None


class TestWaitUnknown:
    def test_wait_unknown_returns_none(self, manager):
        assert manager.wait("nonexistent") is None
