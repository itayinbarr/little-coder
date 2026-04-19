"""Task tools: TaskCreate, TaskUpdate, TaskGet, TaskList — registered into tool_registry."""
from __future__ import annotations

from tool_registry import ToolDef, register_tool
from .store import create_task, get_task, list_tasks, update_task, delete_task
from .types import TaskStatus


# ── Schemas ───────────────────────────────────────────────────────────────────

_TASK_CREATE_SCHEMA = {
    "name": "TaskCreate",
    "description": (
        "Create a new task in the task list. "
        "Use this to track work items, to-dos, and multi-step plans. "
        "Returns the new task's ID and subject."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "A brief title for the task",
            },
            "description": {
                "type": "string",
                "description": "What needs to be done",
            },
            "active_form": {
                "type": "string",
                "description": (
                    "Present-continuous label shown while in_progress "
                    "(e.g. 'Running tests', 'Writing docs')"
                ),
            },
            "metadata": {
                "type": "object",
                "description": "Arbitrary key-value metadata to attach to the task",
            },
        },
        "required": ["subject", "description"],
    },
}

_TASK_UPDATE_SCHEMA = {
    "name": "TaskUpdate",
    "description": (
        "Update an existing task. Can change subject, description, status, owner, "
        "dependency edges (blocks / blocked_by), and metadata. "
        "Set status='deleted' to remove the task. "
        "Valid statuses: pending, in_progress, completed, cancelled, deleted."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The ID of the task to update",
            },
            "subject": {
                "type": "string",
                "description": "New title for the task",
            },
            "description": {
                "type": "string",
                "description": "New description for the task",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "cancelled", "deleted"],
                "description": "New status ('deleted' removes the task)",
            },
            "active_form": {
                "type": "string",
                "description": "Present-continuous label while in_progress",
            },
            "owner": {
                "type": "string",
                "description": "Agent/user responsible for this task",
            },
            "add_blocks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Task IDs that this task now blocks",
            },
            "add_blocked_by": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Task IDs that block this task",
            },
            "metadata": {
                "type": "object",
                "description": "Keys to merge into task metadata (null value = delete key)",
            },
        },
        "required": ["task_id"],
    },
}

_TASK_GET_SCHEMA = {
    "name": "TaskGet",
    "description": "Retrieve a single task by ID. Returns full task details.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The ID of the task to retrieve",
            },
        },
        "required": ["task_id"],
    },
}

_TASK_LIST_SCHEMA = {
    "name": "TaskList",
    "description": (
        "List all tasks. Returns id, subject, status, owner, and pending blockers. "
        "Use this to review the current plan or find the next available task."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


# ── Implementations ────────────────────────────────────────────────────────────

def _task_create(subject: str, description: str, active_form: str = "", metadata: dict = None) -> str:
    task = create_task(subject, description, active_form=active_form, metadata=metadata)
    return f"Task #{task.id} created: {task.subject}"


def _task_update(
    task_id: str,
    subject: str = None,
    description: str = None,
    status: str = None,
    active_form: str = None,
    owner: str = None,
    add_blocks: list = None,
    add_blocked_by: list = None,
    metadata: dict = None,
) -> str:
    # Handle deletion
    if status == "deleted":
        ok = delete_task(task_id)
        if ok:
            return f"Task #{task_id} deleted."
        return f"Error: task #{task_id} not found."

    task, updated_fields = update_task(
        task_id,
        subject=subject,
        description=description,
        status=status,
        active_form=active_form,
        owner=owner,
        add_blocks=add_blocks or [],
        add_blocked_by=add_blocked_by or [],
        metadata=metadata,
    )
    if task is None:
        return f"Error: task #{task_id} not found."
    if not updated_fields:
        return f"Task #{task_id}: no changes (fields already match)."
    return f"Task #{task_id} updated — changed: {', '.join(updated_fields)}."


def _task_get(task_id: str) -> str:
    task = get_task(task_id)
    if task is None:
        return f"Task #{task_id} not found."
    lines = [
        f"Task #{task.id}: {task.subject}",
        f"Status:      {task.status.value}",
        f"Description: {task.description}",
    ]
    if task.owner:
        lines.append(f"Owner:       {task.owner}")
    if task.active_form:
        lines.append(f"Active form: {task.active_form}")
    if task.blocked_by:
        lines.append(f"Blocked by:  #{', #'.join(task.blocked_by)}")
    if task.blocks:
        lines.append(f"Blocks:      #{', #'.join(task.blocks)}")
    if task.metadata:
        lines.append(f"Metadata:    {task.metadata}")
    lines.append(f"Created:     {task.created_at[:19]}")
    lines.append(f"Updated:     {task.updated_at[:19]}")
    return "\n".join(lines)


def _task_list() -> str:
    tasks = list_tasks()
    if not tasks:
        return "No tasks."
    resolved = {t.id for t in tasks if t.status == TaskStatus.COMPLETED}
    lines = []
    for task in tasks:
        pending_blockers = [b for b in task.blocked_by if b not in resolved]
        owner_str   = f" ({task.owner})" if task.owner else ""
        blocked_str = f" [blocked by #{', #'.join(pending_blockers)}]" if pending_blockers else ""
        lines.append(
            f"#{task.id} [{task.status.value}] {task.status_icon()} "
            f"{task.subject}{owner_str}{blocked_str}"
        )
    return "\n".join(lines)


# ── Registration ───────────────────────────────────────────────────────────────

def _register() -> None:
    defs = [
        ToolDef(
            name="TaskCreate",
            schema=_TASK_CREATE_SCHEMA,
            func=lambda p, c: _task_create(
                p["subject"],
                p["description"],
                p.get("active_form", ""),
                p.get("metadata"),
            ),
            read_only=False,
            concurrent_safe=True,
        ),
        ToolDef(
            name="TaskUpdate",
            schema=_TASK_UPDATE_SCHEMA,
            func=lambda p, c: _task_update(
                p["task_id"],
                subject=p.get("subject"),
                description=p.get("description"),
                status=p.get("status"),
                active_form=p.get("active_form"),
                owner=p.get("owner"),
                add_blocks=p.get("add_blocks"),
                add_blocked_by=p.get("add_blocked_by"),
                metadata=p.get("metadata"),
            ),
            read_only=False,
            concurrent_safe=True,
        ),
        ToolDef(
            name="TaskGet",
            schema=_TASK_GET_SCHEMA,
            func=lambda p, c: _task_get(p["task_id"]),
            read_only=True,
            concurrent_safe=True,
        ),
        ToolDef(
            name="TaskList",
            schema=_TASK_LIST_SCHEMA,
            func=lambda p, c: _task_list(),
            read_only=True,
            concurrent_safe=True,
        ),
    ]
    for td in defs:
        register_tool(td)


_register()
