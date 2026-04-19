"""Thread-safe task store: in-memory dict persisted to .little-coder/tasks.json."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .types import Task, TaskStatus

_lock = threading.Lock()

# Tasks are keyed by ID, stored per session in <cwd>/.little-coder/tasks.json
# The store is kept in memory; we reload from disk on first access.

_tasks: dict[str, Task] = {}
_loaded = False


# ── persistence ───────────────────────────────────────────────────────────────

def _tasks_file() -> Path:
    return Path.cwd() / ".little-coder" / "tasks.json"


def _load() -> None:
    global _loaded
    if _loaded:
        return
    f = _tasks_file()
    if f.exists():
        try:
            data = json.loads(f.read_text())
            for item in data.get("tasks", []):
                t = Task.from_dict(item)
                _tasks[t.id] = t
        except Exception:
            pass
    _loaded = True


def _save() -> None:
    f = _tasks_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    data = {"tasks": [t.to_dict() for t in _tasks.values()]}
    f.write_text(json.dumps(data, indent=2))


def _next_id() -> str:
    """Generate a short sequential numeric ID."""
    if not _tasks:
        return "1"
    max_id = max((int(k) for k in _tasks if k.isdigit()), default=0)
    return str(max_id + 1)


# ── public API ────────────────────────────────────────────────────────────────

def create_task(
    subject: str,
    description: str,
    active_form: str = "",
    metadata: dict[str, Any] | None = None,
) -> Task:
    with _lock:
        _load()
        task = Task(
            id=_next_id(),
            subject=subject,
            description=description,
            active_form=active_form,
            metadata=metadata or {},
        )
        _tasks[task.id] = task
        _save()
        return task


def get_task(task_id: str) -> Task | None:
    with _lock:
        _load()
        return _tasks.get(str(task_id))


def list_tasks() -> list[Task]:
    with _lock:
        _load()
        return list(_tasks.values())


def update_task(
    task_id: str,
    subject: str | None = None,
    description: str | None = None,
    status: str | None = None,
    active_form: str | None = None,
    owner: str | None = None,
    add_blocks: list[str] | None = None,
    add_blocked_by: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[Task | None, list[str]]:
    """Update a task. Returns (updated_task, list_of_updated_fields)."""
    with _lock:
        _load()
        task = _tasks.get(str(task_id))
        if task is None:
            return None, []

        updated_fields: list[str] = []

        if subject is not None and subject != task.subject:
            task.subject = subject
            updated_fields.append("subject")

        if description is not None and description != task.description:
            task.description = description
            updated_fields.append("description")

        if active_form is not None and active_form != task.active_form:
            task.active_form = active_form
            updated_fields.append("active_form")

        if owner is not None and owner != task.owner:
            task.owner = owner
            updated_fields.append("owner")

        if status is not None:
            try:
                new_status = TaskStatus(status)
            except ValueError:
                new_status = None
            if new_status is not None and new_status != task.status:
                task.status = new_status
                updated_fields.append("status")

        if metadata is not None:
            for k, v in metadata.items():
                if v is None:
                    task.metadata.pop(k, None)
                else:
                    task.metadata[k] = v
            updated_fields.append("metadata")

        if add_blocks:
            new_blocks = [b for b in add_blocks if b not in task.blocks]
            if new_blocks:
                task.blocks.extend(new_blocks)
                # Also register the reverse edge on the target tasks
                for b_id in new_blocks:
                    target = _tasks.get(str(b_id))
                    if target and str(task_id) not in target.blocked_by:
                        target.blocked_by.append(str(task_id))
                updated_fields.append("blocks")

        if add_blocked_by:
            new_bb = [b for b in add_blocked_by if b not in task.blocked_by]
            if new_bb:
                task.blocked_by.extend(new_bb)
                # Also register the reverse edge
                for blocker_id in new_bb:
                    blocker = _tasks.get(str(blocker_id))
                    if blocker and str(task_id) not in blocker.blocks:
                        blocker.blocks.append(str(task_id))
                updated_fields.append("blocked_by")

        if updated_fields:
            task.updated_at = datetime.now().isoformat()
            _save()

        return task, updated_fields


def delete_task(task_id: str) -> bool:
    with _lock:
        _load()
        task_id = str(task_id)
        if task_id not in _tasks:
            return False
        del _tasks[task_id]
        _save()
        return True


def clear_all_tasks() -> None:
    """Remove all tasks (used in tests)."""
    with _lock:
        _tasks.clear()
        _save()


def reload_from_disk() -> None:
    """Force reload from disk (used in tests)."""
    global _loaded
    with _lock:
        _tasks.clear()
        _loaded = False
        _load()
