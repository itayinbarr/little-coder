"""Checkpoint hooks: intercept Write/Edit/NotebookEdit to back up files before modification.

Import this module after tools are registered to install the hooks.
"""
from __future__ import annotations

from pathlib import Path

from . import store

# ── Module state ────────────────────────────────────────────────────────────

_current_session_id: str | None = None
_tracked_edits: dict[str, str | None] = {}   # file_path → backup_filename


def set_session(session_id: str) -> None:
    global _current_session_id
    _current_session_id = session_id


def get_tracked_edits() -> dict[str, str | None]:
    """Return the current interval's tracked edits (for make_snapshot)."""
    return dict(_tracked_edits)


def reset_tracked() -> None:
    """Clear tracked edits after a snapshot is created."""
    _tracked_edits.clear()


# ── Backup logic ────────────────────────────────────────────────────────────

def _backup_before_write(file_path: str) -> None:
    """Back up a file before it is modified (first-write-wins per snapshot interval)."""
    if _current_session_id is None:
        return
    if file_path in _tracked_edits:
        return  # already backed up this interval

    backup_name = store.track_file_edit(_current_session_id, file_path)
    _tracked_edits[file_path] = backup_name


# ── Hook installation ───────────────────────────────────────────────────────

_hooks_installed = False


def install_hooks() -> None:
    """Wrap Write/Edit/NotebookEdit tool functions to call backup before execution."""
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True

    from tool_registry import get_tool

    # Hook Write
    write_tool = get_tool("Write")
    if write_tool:
        original_write = write_tool.func
        def hooked_write(params, config):
            fp = params.get("file_path", "")
            if fp:
                _backup_before_write(fp)
            return original_write(params, config)
        write_tool.func = hooked_write

    # Hook Edit
    edit_tool = get_tool("Edit")
    if edit_tool:
        original_edit = edit_tool.func
        def hooked_edit(params, config):
            fp = params.get("file_path", "")
            if fp:
                _backup_before_write(fp)
            return original_edit(params, config)
        edit_tool.func = hooked_edit

    # Hook NotebookEdit
    nb_tool = get_tool("NotebookEdit")
    if nb_tool:
        original_nb = nb_tool.func
        def hooked_nb(params, config):
            fp = params.get("notebook_path", "")
            if fp:
                _backup_before_write(fp)
            return original_nb(params, config)
        nb_tool.func = hooked_nb
