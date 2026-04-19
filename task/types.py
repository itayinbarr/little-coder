"""Task system types: Task dataclass, TaskStatus enum."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING     = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    CANCELLED   = "cancelled"


VALID_STATUSES = {s.value for s in TaskStatus}


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    active_form: str = ""          # e.g. "Running tests"
    owner: str = ""
    blocks: list[str] = field(default_factory=list)      # IDs this task blocks
    blocked_by: list[str] = field(default_factory=list)  # IDs that block this task
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # ── serialization ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "subject":      self.subject,
            "description":  self.description,
            "status":       self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "active_form":  self.active_form,
            "owner":        self.owner,
            "blocks":       self.blocks,
            "blocked_by":   self.blocked_by,
            "metadata":     self.metadata,
            "created_at":   self.created_at,
            "updated_at":   self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        status_raw = data.get("status", "pending")
        try:
            status = TaskStatus(status_raw)
        except ValueError:
            status = TaskStatus.PENDING
        return cls(
            id=data["id"],
            subject=data.get("subject", ""),
            description=data.get("description", ""),
            status=status,
            active_form=data.get("active_form", ""),
            owner=data.get("owner", ""),
            blocks=data.get("blocks", []),
            blocked_by=data.get("blocked_by", []),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )

    # ── display ────────────────────────────────────────────────────────────────

    def status_icon(self) -> str:
        return {
            TaskStatus.PENDING:     "○",
            TaskStatus.IN_PROGRESS: "●",
            TaskStatus.COMPLETED:   "✓",
            TaskStatus.CANCELLED:   "✗",
        }.get(self.status, "?")

    def one_line(self, resolved_ids: set[str] | None = None) -> str:
        owner_str = f" ({self.owner})" if self.owner else ""
        pending_blockers = [
            b for b in self.blocked_by
            if resolved_ids is None or b not in resolved_ids
        ]
        blocked_str = (
            f" [blocked by #{', #'.join(pending_blockers)}]"
            if pending_blockers else ""
        )
        return f"#{self.id} [{self.status.value}] {self.status_icon()} {self.subject}{owner_str}{blocked_str}"
