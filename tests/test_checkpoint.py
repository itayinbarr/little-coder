"""Tests for the checkpoint system."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Fixtures ─────────────────────────────────────────────────────────────────

@dataclass
class FakeState:
    messages: list = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    turn_count: int = 0


@pytest.fixture
def tmp_home(tmp_path):
    """Redirect ~/.little-coder/checkpoints to a temp directory."""
    ckpt_root = tmp_path / ".little-coder" / "checkpoints"
    ckpt_root.mkdir(parents=True)
    with patch("checkpoint.store._checkpoints_root", return_value=ckpt_root):
        yield tmp_path, ckpt_root


@pytest.fixture(autouse=True)
def reset_versions():
    """Reset file version counters between tests."""
    from checkpoint.store import reset_file_versions
    reset_file_versions()
    yield
    reset_file_versions()


# ── types.py tests ───────────────────────────────────────────────────────────

class TestTypes:
    def test_file_backup_roundtrip(self):
        from checkpoint.types import FileBackup
        fb = FileBackup(backup_filename="abc123@v1", version=1, backup_time="2024-01-01T00:00:00")
        d = fb.to_dict()
        fb2 = FileBackup.from_dict(d)
        assert fb2.backup_filename == fb.backup_filename
        assert fb2.version == fb.version
        assert fb2.backup_time == fb.backup_time

    def test_file_backup_none_filename(self):
        from checkpoint.types import FileBackup
        fb = FileBackup(backup_filename=None, version=0, backup_time="2024-01-01T00:00:00")
        d = fb.to_dict()
        fb2 = FileBackup.from_dict(d)
        assert fb2.backup_filename is None

    def test_snapshot_roundtrip(self):
        from checkpoint.types import Snapshot, FileBackup
        fb = FileBackup(backup_filename="abc@v1", version=1, backup_time="2024-01-01")
        snap = Snapshot(
            id=1, session_id="test123", created_at="2024-01-01",
            turn_count=3, message_index=5, user_prompt_preview="hello world",
            token_snapshot={"input": 100, "output": 50},
            file_backups={"/tmp/test.py": fb},
        )
        d = snap.to_dict()
        snap2 = Snapshot.from_dict(d)
        assert snap2.id == 1
        assert snap2.session_id == "test123"
        assert snap2.turn_count == 3
        assert snap2.message_index == 5
        assert "/tmp/test.py" in snap2.file_backups
        assert snap2.file_backups["/tmp/test.py"].backup_filename == "abc@v1"


# ── store.py tests ───────────────────────────────────────────────────────────

class TestStore:
    def test_track_file_edit_existing_file(self, tmp_home, tmp_path):
        from checkpoint import store
        # Create a file to back up
        test_file = tmp_path / "hello.py"
        test_file.write_text("print('hello')", encoding="utf-8")

        result = store.track_file_edit("sess1", str(test_file))
        assert result is not None
        assert "@v" in result

        # Verify the backup was actually created
        bdir = store._backups_dir("sess1")
        backup_file = bdir / result
        assert backup_file.exists()
        assert backup_file.read_text(encoding="utf-8") == "print('hello')"

    def test_track_file_edit_nonexistent(self, tmp_home, tmp_path):
        from checkpoint import store
        result = store.track_file_edit("sess1", str(tmp_path / "nope.py"))
        assert result is None

    def test_track_file_edit_large_file_skipped(self, tmp_home, tmp_path):
        from checkpoint import store
        big_file = tmp_path / "big.bin"
        big_file.write_bytes(b"x" * (2 * 1024 * 1024))  # 2MB
        result = store.track_file_edit("sess1", str(big_file))
        assert result is None

    def test_make_snapshot_basic(self, tmp_home, tmp_path):
        from checkpoint import store
        state = FakeState(
            messages=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
            turn_count=1,
            total_input_tokens=100,
            total_output_tokens=50,
        )
        snap = store.make_snapshot("sess1", state, {}, "hi", tracked_edits=None)
        assert snap is not None
        assert snap.id == 1
        assert snap.turn_count == 1
        assert snap.message_index == 2

    def test_make_snapshot_incremental(self, tmp_home, tmp_path):
        from checkpoint import store
        test_file = tmp_path / "code.py"
        test_file.write_text("v1", encoding="utf-8")

        state = FakeState(messages=[{"role": "user", "content": "a"}], turn_count=1)

        # First snapshot with a tracked edit
        backup_name = store.track_file_edit("sess1", str(test_file))
        snap1 = store.make_snapshot(
            "sess1", state, {}, "first",
            tracked_edits={str(test_file): backup_name},
        )
        assert str(test_file) in snap1.file_backups

        # Second snapshot — no edits, should carry forward the same file reference
        state.messages.append({"role": "user", "content": "b"})
        state.turn_count = 2
        snap2 = store.make_snapshot("sess1", state, {}, "second", tracked_edits=None)
        assert snap2.id == 2
        assert str(test_file) in snap2.file_backups
        # Carried forward from snap1 (same backup since no edits)
        assert snap2.file_backups[str(test_file)].backup_filename == snap1.file_backups[str(test_file)].backup_filename

    def test_list_snapshots(self, tmp_home):
        from checkpoint import store
        state = FakeState(messages=[], turn_count=0)
        store.make_snapshot("sess1", state, {}, "one")
        store.make_snapshot("sess1", state, {}, "two")
        snaps = store.list_snapshots("sess1")
        assert len(snaps) == 2
        assert snaps[0]["id"] == 1
        assert snaps[1]["id"] == 2

    def test_get_snapshot(self, tmp_home):
        from checkpoint import store
        state = FakeState(messages=[], turn_count=0)
        store.make_snapshot("sess1", state, {}, "test")
        snap = store.get_snapshot("sess1", 1)
        assert snap is not None
        assert snap.user_prompt_preview == "test"
        assert store.get_snapshot("sess1", 99) is None

    def test_rewind_files(self, tmp_home, tmp_path):
        from checkpoint import store
        test_file = tmp_path / "code.py"
        test_file.write_text("original", encoding="utf-8")

        state = FakeState(messages=[], turn_count=0)
        backup_name = store.track_file_edit("sess1", str(test_file))
        store.make_snapshot(
            "sess1", state, {}, "before edit",
            tracked_edits={str(test_file): backup_name},
        )

        # Modify the file
        test_file.write_text("modified", encoding="utf-8")
        assert test_file.read_text(encoding="utf-8") == "modified"

        # Rewind
        results = store.rewind_files("sess1", 1)
        assert len(results) == 1
        assert "restored" in results[0]
        assert test_file.read_text(encoding="utf-8") == "original"

    def test_rewind_deletes_new_file(self, tmp_home, tmp_path):
        from checkpoint import store
        new_file = tmp_path / "new.py"

        state = FakeState(messages=[], turn_count=0)
        # Snapshot where file doesn't exist (backup_filename=None)
        store.make_snapshot(
            "sess1", state, {}, "before create",
            tracked_edits={str(new_file): None},
        )

        # Create the file
        new_file.write_text("new content", encoding="utf-8")
        assert new_file.exists()

        # Rewind should delete it
        results = store.rewind_files("sess1", 1)
        assert any("deleted" in r for r in results)
        assert not new_file.exists()

    def test_max_snapshots_sliding_window(self, tmp_home):
        from checkpoint import store
        from checkpoint.types import MAX_SNAPSHOTS
        state = FakeState(messages=[], turn_count=0)
        for i in range(MAX_SNAPSHOTS + 10):
            store.make_snapshot("sess1", state, {}, f"snap {i}")
        snaps = store.list_snapshots("sess1")
        assert len(snaps) == MAX_SNAPSHOTS

    def test_files_changed_since(self, tmp_home, tmp_path):
        from checkpoint import store
        f1 = tmp_path / "a.py"
        f1.write_text("a", encoding="utf-8")
        f2 = tmp_path / "b.py"
        f2.write_text("b", encoding="utf-8")

        state = FakeState(messages=[], turn_count=0)
        b1 = store.track_file_edit("sess1", str(f1))
        store.make_snapshot("sess1", state, {}, "s1", tracked_edits={str(f1): b1})

        b2 = store.track_file_edit("sess1", str(f2))
        store.make_snapshot("sess1", state, {}, "s2", tracked_edits={str(f2): b2})

        changed = store.files_changed_since("sess1", 1)
        assert str(f2) in changed
        # f1 was not changed after snapshot 1 (it was already in snap 1)

    def test_delete_session_checkpoints(self, tmp_home):
        from checkpoint import store
        state = FakeState(messages=[], turn_count=0)
        store.make_snapshot("sess1", state, {}, "test")
        assert store.delete_session_checkpoints("sess1")
        assert store.list_snapshots("sess1") == []

    def test_cleanup_old_sessions(self, tmp_home):
        from checkpoint import store
        # Create a session dir and make it old
        old_dir = store._session_dir("old_sess")
        old_dir.mkdir(parents=True, exist_ok=True)
        # Set mtime to 60 days ago
        old_time = os.path.getmtime(str(old_dir)) - (60 * 86400)
        os.utime(str(old_dir), (old_time, old_time))

        removed = store.cleanup_old_sessions(max_age_days=30)
        assert removed == 1


# ── hooks.py tests ───────────────────────────────────────────────────────────

class TestHooks:
    def test_set_session_and_tracking(self, tmp_home, tmp_path):
        from checkpoint import hooks, store

        hooks.set_session("sess_test")
        hooks.reset_tracked()

        test_file = tmp_path / "test.py"
        test_file.write_text("content", encoding="utf-8")

        hooks._backup_before_write(str(test_file))
        edits = hooks.get_tracked_edits()
        assert str(test_file) in edits

        # Second call should be no-op (first-write-wins)
        hooks._backup_before_write(str(test_file))
        edits2 = hooks.get_tracked_edits()
        assert edits2 == edits

    def test_reset_tracked(self, tmp_home, tmp_path):
        from checkpoint import hooks

        hooks.set_session("sess_test2")
        hooks.reset_tracked()  # clear state from previous test

        test_file = tmp_path / "test2.py"
        test_file.write_text("content", encoding="utf-8")

        hooks._backup_before_write(str(test_file))
        assert len(hooks.get_tracked_edits()) == 1

        hooks.reset_tracked()
        assert len(hooks.get_tracked_edits()) == 0

    def test_install_hooks_wraps_tools(self):
        """Verify install_hooks wraps Write/Edit/NotebookEdit without error."""
        from checkpoint import hooks
        # Hooks are already installed by tools.py import, just verify no crash
        # and that the function is idempotent
        hooks._hooks_installed = False
        hooks.install_hooks()
        assert hooks._hooks_installed


# ── Integration test ─────────────────────────────────────────────────────────

class TestIntegration:
    def test_write_snapshot_rewind_cycle(self, tmp_home, tmp_path):
        """Simulate: write file → snapshot → modify → rewind → verify restored."""
        from checkpoint import store, hooks

        session_id = "integ_test"
        hooks.set_session(session_id)
        hooks.reset_tracked()

        # Create original file
        test_file = tmp_path / "app.py"
        test_file.write_text("def main(): pass", encoding="utf-8")

        # Simulate Write tool hook: backup before editing
        hooks._backup_before_write(str(test_file))

        # Create snapshot
        state = FakeState(
            messages=[
                {"role": "user", "content": "write code"},
                {"role": "assistant", "content": "done"},
            ],
            turn_count=1,
            total_input_tokens=200,
            total_output_tokens=100,
        )
        tracked = hooks.get_tracked_edits()
        snap = store.make_snapshot(session_id, state, {}, "write code", tracked_edits=tracked)
        hooks.reset_tracked()
        assert snap.id == 1

        # Now modify the file (simulating a second turn)
        test_file.write_text("def main(): print('hello')", encoding="utf-8")
        hooks._backup_before_write(str(test_file))

        state.messages.extend([
            {"role": "user", "content": "change it"},
            {"role": "assistant", "content": "changed"},
        ])
        state.turn_count = 2
        tracked2 = hooks.get_tracked_edits()
        snap2 = store.make_snapshot(session_id, state, {}, "change it", tracked_edits=tracked2)
        hooks.reset_tracked()
        assert snap2.id == 2

        # Verify current state
        assert test_file.read_text(encoding="utf-8") == "def main(): print('hello')"
        assert len(state.messages) == 4

        # Rewind to snapshot 1
        results = store.rewind_files(session_id, 1)
        assert any("restored" in r for r in results)
        assert test_file.read_text(encoding="utf-8") == "def main(): pass"

        # Conversation rewind
        state.messages = state.messages[:snap.message_index]
        state.turn_count = snap.turn_count
        assert len(state.messages) == 2
        assert state.turn_count == 1

    def test_initial_snapshot(self, tmp_home):
        """Initial snapshot should be id=1 with empty messages and prompt '(initial state)'."""
        from checkpoint import store

        state = FakeState(messages=[], turn_count=0)
        snap = store.make_snapshot("init_test", state, {}, "(initial state)", tracked_edits=None)
        assert snap.id == 1
        assert snap.message_index == 0
        assert snap.turn_count == 0
        assert snap.user_prompt_preview == "(initial state)"
        assert snap.file_backups == {}

    def test_throttle_skips_when_no_changes(self, tmp_home):
        """Snapshot should be skipped when no files changed and message_index is same."""
        from checkpoint import store

        state = FakeState(messages=[], turn_count=0)
        # Initial snapshot
        store.make_snapshot("throttle_test", state, {}, "(initial state)")

        # Same state, no tracked edits — should be skippable
        snaps = store.list_snapshots("throttle_test")
        assert len(snaps) == 1
        last_msg_idx = snaps[-1].get("message_index", -1)
        # Simulate throttle check: no tracked edits + same message count → skip
        assert len(state.messages) == last_msg_idx  # would skip

    def test_throttle_creates_when_messages_grew(self, tmp_home):
        """Snapshot should be created when messages grew even without file changes."""
        from checkpoint import store

        state = FakeState(messages=[], turn_count=0)
        store.make_snapshot("throttle2", state, {}, "(initial state)")

        # Messages grew (a turn happened)
        state.messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        state.turn_count = 1

        snaps_before = store.list_snapshots("throttle2")
        last_msg_idx = snaps_before[-1].get("message_index", -1)
        # message count changed → should NOT skip
        assert len(state.messages) != last_msg_idx

        store.make_snapshot("throttle2", state, {}, "hello", tracked_edits=None)
        snaps_after = store.list_snapshots("throttle2")
        assert len(snaps_after) == 2

    def test_throttle_conversation_rewind_works(self, tmp_home):
        """After throttled snapshots, conversation rewind via message_index still works."""
        from checkpoint import store

        state = FakeState(messages=[], turn_count=0)
        # Snap 1: initial
        store.make_snapshot("rewind_conv", state, {}, "(initial state)")

        # Snap 2: first turn (no files, but messages grew)
        state.messages = [
            {"role": "user", "content": "do something"},
            {"role": "assistant", "content": "done"},
        ]
        state.turn_count = 1
        store.make_snapshot("rewind_conv", state, {}, "do something")

        # Snap 3: second turn (no files, messages grew again)
        state.messages.extend([
            {"role": "user", "content": "do more"},
            {"role": "assistant", "content": "more done"},
        ])
        state.turn_count = 2
        store.make_snapshot("rewind_conv", state, {}, "do more")

        # Verify we have 3 snapshots
        snaps = store.list_snapshots("rewind_conv")
        assert len(snaps) == 3

        # Rewind conversation to snap 2
        snap2 = store.get_snapshot("rewind_conv", 2)
        assert snap2.message_index == 2
        state.messages = state.messages[:snap2.message_index]
        state.turn_count = snap2.turn_count
        assert len(state.messages) == 2
        assert state.messages[-1]["content"] == "done"
        assert state.turn_count == 1

        # Rewind to snap 1 (initial)
        snap1 = store.get_snapshot("rewind_conv", 1)
        assert snap1.message_index == 0
        state.messages = state.messages[:snap1.message_index]
        state.turn_count = snap1.turn_count
        assert len(state.messages) == 0
        assert state.turn_count == 0
