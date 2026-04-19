"""Checkpoint system: automatic file snapshots with rewind support."""
from .types import FileBackup, Snapshot, MAX_SNAPSHOTS
from .store import (
    track_file_edit,
    make_snapshot,
    list_snapshots,
    get_snapshot,
    rewind_files,
    files_changed_since,
    delete_session_checkpoints,
    cleanup_old_sessions,
    reset_file_versions,
)
from .hooks import (
    set_session,
    get_tracked_edits,
    reset_tracked,
    install_hooks,
)

__all__ = [
    "FileBackup", "Snapshot", "MAX_SNAPSHOTS",
    "track_file_edit", "make_snapshot", "list_snapshots", "get_snapshot",
    "rewind_files", "files_changed_since",
    "delete_session_checkpoints", "cleanup_old_sessions", "reset_file_versions",
    "set_session", "get_tracked_edits", "reset_tracked", "install_hooks",
]
