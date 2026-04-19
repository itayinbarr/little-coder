"""Tests for the task package (task/)."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from task.types import Task, TaskStatus
from task import (
    create_task, get_task, list_tasks, update_task,
    delete_task, clear_all_tasks,
)
import task.store as _store


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Each test gets a fresh in-memory + on-disk task store."""
    monkeypatch.setattr(_store, "_tasks", {})
    monkeypatch.setattr(_store, "_loaded", False)
    monkeypatch.setattr(_store, "_tasks_file", lambda: tmp_path / ".little-coder" / "tasks.json")
    yield
    _store._tasks.clear()
    _store._loaded = False


# ── types ─────────────────────────────────────────────────────────────────────

class TestTaskTypes:
    def test_default_status(self):
        t = Task(id="1", subject="Do X", description="Details")
        assert t.status == TaskStatus.PENDING

    def test_status_icon(self):
        t = Task(id="1", subject="x", description="y")
        t.status = TaskStatus.COMPLETED
        assert t.status_icon() == "✓"

    def test_to_dict_roundtrip(self):
        t = Task(id="42", subject="Fix bug", description="In module X",
                 status=TaskStatus.IN_PROGRESS, owner="alice",
                 blocks=["2"], blocked_by=["1"])
        d = t.to_dict()
        assert d["id"] == "42"
        assert d["status"] == "in_progress"
        assert d["owner"] == "alice"
        restored = Task.from_dict(d)
        assert restored.id == "42"
        assert restored.status == TaskStatus.IN_PROGRESS
        assert restored.blocks == ["2"]

    def test_from_dict_unknown_status_defaults_pending(self):
        t = Task.from_dict({"id": "1", "subject": "x", "description": "y", "status": "bogus"})
        assert t.status == TaskStatus.PENDING

    def test_one_line_no_blockers(self):
        t = Task(id="1", subject="Write tests", description="")
        line = t.one_line()
        assert "#1" in line
        assert "Write tests" in line

    def test_one_line_with_blockers(self):
        t = Task(id="3", subject="Deploy", description="", blocked_by=["1", "2"])
        line = t.one_line(resolved_ids=set())
        assert "blocked by" in line

    def test_one_line_resolved_blockers_hidden(self):
        t = Task(id="3", subject="Deploy", description="", blocked_by=["1"])
        line = t.one_line(resolved_ids={"1"})
        assert "blocked" not in line


# ── store ─────────────────────────────────────────────────────────────────────

class TestTaskStore:
    def test_create_returns_task(self):
        t = create_task("Write docs", "Document everything")
        assert t.id == "1"
        assert t.subject == "Write docs"
        assert t.status == TaskStatus.PENDING

    def test_ids_are_sequential(self):
        t1 = create_task("A", "")
        t2 = create_task("B", "")
        t3 = create_task("C", "")
        assert t1.id == "1"
        assert t2.id == "2"
        assert t3.id == "3"

    def test_get_returns_task(self):
        t = create_task("Buy milk", "From the store")
        fetched = get_task(t.id)
        assert fetched is not None
        assert fetched.subject == "Buy milk"

    def test_get_unknown_returns_none(self):
        assert get_task("999") is None

    def test_list_returns_all(self):
        create_task("A", "")
        create_task("B", "")
        tasks = list_tasks()
        assert len(tasks) == 2

    def test_list_empty(self):
        assert list_tasks() == []

    def test_update_status(self):
        t = create_task("Fix bug", "In module A")
        updated, fields = update_task(t.id, status="in_progress")
        assert updated is not None
        assert updated.status == TaskStatus.IN_PROGRESS
        assert "status" in fields

    def test_update_subject_and_description(self):
        t = create_task("Old title", "Old desc")
        updated, fields = update_task(t.id, subject="New title", description="New desc")
        assert updated.subject == "New title"
        assert "subject" in fields
        assert "description" in fields

    def test_update_owner(self):
        t = create_task("Deploy", "")
        updated, fields = update_task(t.id, owner="alice")
        assert updated.owner == "alice"
        assert "owner" in fields

    def test_update_no_changes_returns_empty_fields(self):
        t = create_task("Same", "desc")
        _, fields = update_task(t.id, subject="Same")
        assert "subject" not in fields

    def test_update_unknown_task(self):
        task, fields = update_task("999", status="completed")
        assert task is None
        assert fields == []

    def test_update_add_blocks(self):
        t1 = create_task("Step 1", "")
        t2 = create_task("Step 2", "")
        updated, fields = update_task(t1.id, add_blocks=[t2.id])
        assert t2.id in updated.blocks
        assert "blocks" in fields
        # Reverse edge: t2 should now be blocked_by t1
        t2_fetched = get_task(t2.id)
        assert t1.id in t2_fetched.blocked_by

    def test_update_add_blocked_by(self):
        t1 = create_task("Blocker", "")
        t2 = create_task("Blocked", "")
        updated, fields = update_task(t2.id, add_blocked_by=[t1.id])
        assert t1.id in updated.blocked_by
        assert "blocked_by" in fields
        # Reverse edge
        t1_fetched = get_task(t1.id)
        assert t2.id in t1_fetched.blocks

    def test_update_metadata_merge(self):
        t = create_task("Task", "", metadata={"a": 1, "b": 2})
        updated, _ = update_task(t.id, metadata={"b": None, "c": 3})
        assert "b" not in updated.metadata
        assert updated.metadata["a"] == 1
        assert updated.metadata["c"] == 3

    def test_delete_removes_task(self):
        t = create_task("Temp", "")
        removed = delete_task(t.id)
        assert removed is True
        assert get_task(t.id) is None

    def test_delete_unknown(self):
        assert delete_task("999") is False

    def test_persistence_round_trip(self, tmp_path):
        """Tasks saved to disk are re-loaded correctly."""
        create_task("Persisted", "Should survive reload")
        # Force reload
        _store._tasks.clear()
        _store._loaded = False
        tasks = list_tasks()
        assert len(tasks) == 1
        assert tasks[0].subject == "Persisted"

    def test_clear_all(self):
        create_task("A", "")
        create_task("B", "")
        clear_all_tasks()
        assert list_tasks() == []

    def test_thread_safety(self):
        """Concurrent creates should produce unique IDs."""
        errors = []
        def worker():
            try:
                create_task("Concurrent", "")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert not errors
        tasks = list_tasks()
        ids = [t.id for t in tasks]
        assert len(ids) == len(set(ids)), "duplicate IDs detected"


# ── tool functions ────────────────────────────────────────────────────────────

class TestTaskToolFunctions:
    """Test the string-returning functions used by the registered tools."""

    def test_task_create_tool(self):
        from task.tools import _task_create
        result = _task_create("Write README", "Add installation section")
        assert "#1" in result
        assert "Write README" in result

    def test_task_update_tool_status(self):
        from task.tools import _task_create, _task_update
        _task_create("Fix lint", "Run ruff")
        result = _task_update("1", status="in_progress")
        assert "in_progress" in result or "updated" in result.lower()

    def test_task_update_tool_delete(self):
        from task.tools import _task_create, _task_update
        _task_create("Temp task", "Will be deleted")
        result = _task_update("1", status="deleted")
        assert "deleted" in result.lower()
        assert get_task("1") is None

    def test_task_update_not_found(self):
        from task.tools import _task_update
        result = _task_update("999", status="completed")
        assert "not found" in result.lower()

    def test_task_get_tool(self):
        from task.tools import _task_create, _task_get
        _task_create("Review PR", "Check the diff carefully")
        result = _task_get("1")
        assert "Review PR" in result
        assert "pending" in result

    def test_task_get_not_found(self):
        from task.tools import _task_get
        result = _task_get("999")
        assert "not found" in result.lower()

    def test_task_list_tool_empty(self):
        from task.tools import _task_list
        result = _task_list()
        assert "No tasks" in result

    def test_task_list_tool_multiple(self):
        from task.tools import _task_create, _task_list
        _task_create("Step 1", "First thing")
        _task_create("Step 2", "Second thing")
        result = _task_list()
        assert "#1" in result
        assert "#2" in result

    def test_task_list_hides_resolved_blockers(self):
        from task.tools import _task_create, _task_update, _task_list
        _task_create("Step A", "")           # id=1 (blocker)
        _task_create("Step B", "")           # id=2 (depends on 1)
        _task_update("2", add_blocked_by=["1"])
        _task_update("1", status="completed")
        result = _task_list()
        # Task 2 should NOT show "[blocked by ...]" since its blocker is now resolved
        lines = [l for l in result.splitlines() if "#2" in l]
        assert lines
        assert "[blocked by" not in lines[0].lower()

