"""End-to-end checkpoint test: simulate a real user session."""
import os, sys, uuid, shutil, tempfile
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime

# ── Setup: use a temp dir as workspace ──
tmpdir = Path(tempfile.mkdtemp(prefix="ckpt_e2e_"))
print(f"Workspace: {tmpdir}")

# Patch checkpoints root to temp
import checkpoint.store as store
_orig_root = store._checkpoints_root
store._checkpoints_root = lambda: tmpdir / ".little-coder" / "checkpoints"

import checkpoint as ckpt
from checkpoint.hooks import set_session, get_tracked_edits, reset_tracked, _backup_before_write

# ── Simulate AgentState ──
@dataclass
class AgentState:
    messages: list = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    turn_count: int = 0

state = AgentState()
session_id = uuid.uuid4().hex[:8]
config = {"_session_id": session_id}

SEP = "=" * 60

def auto_snapshot(user_input):
    """Same logic as little_coder.py auto-snapshot with throttle."""
    tracked = get_tracked_edits()
    last_snaps = ckpt.list_snapshots(session_id)
    skip = False
    if not tracked and last_snaps:
        if len(state.messages) == last_snaps[-1].get("message_index", -1):
            skip = True
    snap = None
    if not skip:
        snap = ckpt.make_snapshot(session_id, state, config, user_input, tracked_edits=tracked)
    reset_tracked()
    return snap, skip


# ── Step 1: Init ──
print(f"\n{SEP}")
print("STEP 1: Initialize session & create initial snapshot")
print(SEP)
set_session(session_id)
ckpt.cleanup_old_sessions()
snap0 = ckpt.make_snapshot(session_id, state, config, "(initial state)", tracked_edits=None)
print(f"  Initial snapshot: id={snap0.id}, message_index={snap0.message_index}")
assert snap0.id == 1 and snap0.message_index == 0 and snap0.file_backups == {}
print("  PASS")

# ── Step 2: Turn 1 — AI writes app.py ──
print(f"\n{SEP}")
print("STEP 2: Turn 1 - AI writes app.py")
print(SEP)
app_py = tmpdir / "app.py"
_backup_before_write(str(app_py))  # doesn't exist yet → None
app_py.write_text("def main():\n    print('hello')\n", encoding="utf-8")
print(f"  Created app.py")

state.messages = [
    {"role": "user", "content": "Create app.py"},
    {"role": "assistant", "content": "Done."},
]
state.turn_count = 1
state.total_input_tokens = 150
state.total_output_tokens = 80

snap1, skipped = auto_snapshot("Create app.py")
assert not skipped and snap1 is not None
print(f"  Snapshot: id={snap1.id}, msg_idx={snap1.message_index}, files={len(snap1.file_backups)}")
assert snap1.message_index == 2
assert str(app_py) in snap1.file_backups
# backup_filename should NOT be None — snapshot captures post-edit state
assert snap1.file_backups[str(app_py)].backup_filename is not None
print("  PASS")

# ── Step 3: Turn 2 — AI edits app.py ──
print(f"\n{SEP}")
print("STEP 3: Turn 2 - AI edits app.py (add error handling)")
print(SEP)
_backup_before_write(str(app_py))  # backs up current v1
app_py.write_text("def main():\n    try:\n        print('hello')\n    except Exception as e:\n        print(e)\n", encoding="utf-8")
print(f"  Modified app.py (added try/except)")

state.messages.extend([
    {"role": "user", "content": "Add error handling"},
    {"role": "assistant", "content": "Added try/except."},
])
state.turn_count = 2
state.total_input_tokens = 300
state.total_output_tokens = 160

snap2, skipped = auto_snapshot("Add error handling")
assert not skipped and snap2 is not None
print(f"  Snapshot: id={snap2.id}, msg_idx={snap2.message_index}")
# This time backup_filename should NOT be None (file existed before edit)
assert snap2.file_backups[str(app_py)].backup_filename is not None
print("  PASS")

# ── Step 4: Turn 3 — conversation only ──
print(f"\n{SEP}")
print("STEP 4: Turn 3 - conversation only (no file edits)")
print(SEP)
state.messages.extend([
    {"role": "user", "content": "Explain the code"},
    {"role": "assistant", "content": "It prints hello with error handling."},
])
state.turn_count = 3

snap3, skipped = auto_snapshot("Explain the code")
assert not skipped, "Should create snapshot — messages grew"
print(f"  Snapshot: id={snap3.id}, msg_idx={snap3.message_index} (conversation-only)")
assert snap3.message_index == 6
print("  PASS")

# ── Step 5: Throttle — nothing happened ──
print(f"\n{SEP}")
print("STEP 5: Throttle test - no changes at all -> should SKIP")
print(SEP)
_, skipped = auto_snapshot("Explain the code")
assert skipped, "Should be skipped — nothing changed"
print(f"  Correctly skipped (messages={len(state.messages)}, last snapshot msg_idx=6)")
print("  PASS")

# ── Step 6: /checkpoint list ──
print(f"\n{SEP}")
print("STEP 6: /checkpoint — list all snapshots")
print(SEP)
snaps = ckpt.list_snapshots(session_id)
print(f"  Checkpoints ({len(snaps)} total):")
for s in snaps:
    t = datetime.fromisoformat(s["created_at"]).strftime("%H:%M:%S")
    p = s["user_prompt_preview"][:40] or "(none)"
    print(f"    #{s['id']:<3} [turn {s['turn_count']}] msg_idx={s['message_index']}  {t}  \"{p}\"")
assert len(snaps) == 4  # initial + 3 turns (step 5 was skipped)
print("  PASS")

# ── Step 7: Rewind files+conversation to snap #2 ──
print(f"\n{SEP}")
print("STEP 7: /checkpoint 2 — full rewind (files + conversation)")
print(SEP)
print(f"  Before: {len(state.messages)} msgs, app.py has try/except={('try:' in app_py.read_text())}")
assert "try:" in app_py.read_text()

snap_target = ckpt.get_snapshot(session_id, 2)
file_results = ckpt.rewind_files(session_id, 2)
for r in file_results:
    print(f"    {r}")

state.messages = state.messages[:snap_target.message_index]
state.turn_count = snap_target.turn_count
state.total_input_tokens = snap_target.token_snapshot.get("input", 0)
state.total_output_tokens = snap_target.token_snapshot.get("output", 0)

content = app_py.read_text(encoding="utf-8")
print(f"  After:  {len(state.messages)} msgs, turn={state.turn_count}")
print(f"  app.py: {content.strip()!r}")
assert len(state.messages) == 2
assert state.turn_count == 1
assert "try:" not in content
assert "print('hello')" in content
print("  PASS")

# ── Step 8: Rewind to initial state (snap #1) ──
print(f"\n{SEP}")
print("STEP 8: /checkpoint 1 — rewind to initial state")
print(SEP)
snap_init = ckpt.get_snapshot(session_id, 1)
file_results = ckpt.rewind_files(session_id, 1)
print(f"  File results: {file_results}")

state.messages = state.messages[:snap_init.message_index]
state.turn_count = snap_init.turn_count

print(f"  After:  {len(state.messages)} msgs, turn={state.turn_count}")
assert len(state.messages) == 0
assert state.turn_count == 0
print("  PASS")

# ── Step 9: Conversation-only rewind to snap #4 ──
print(f"\n{SEP}")
print("STEP 9: Conversation-only rewind to snap #4 (turn 3)")
print(SEP)
# Rebuild messages as if session continued
state.messages = [
    {"role": "user", "content": "Create app.py"},
    {"role": "assistant", "content": "Done."},
    {"role": "user", "content": "Add error handling"},
    {"role": "assistant", "content": "Added try/except."},
    {"role": "user", "content": "Explain the code"},
    {"role": "assistant", "content": "It prints hello with error handling."},
    {"role": "user", "content": "Extra question"},
    {"role": "assistant", "content": "Extra answer"},
]
state.turn_count = 4

snap4 = ckpt.get_snapshot(session_id, 4)
print(f"  Snap #4: msg_idx={snap4.message_index}, turn={snap4.turn_count}")
state.messages = state.messages[:snap4.message_index]
state.turn_count = snap4.turn_count
print(f"  After:  {len(state.messages)} msgs")
assert len(state.messages) == 6
assert state.messages[-1]["content"] == "It prints hello with error handling."
print("  PASS")

# ── Step 10: /checkpoint clear ──
print(f"\n{SEP}")
print("STEP 10: /checkpoint clear + cleanup")
print(SEP)
ckpt.delete_session_checkpoints(session_id)
assert ckpt.list_snapshots(session_id) == []
shutil.rmtree(str(tmpdir), ignore_errors=True)
store._checkpoints_root = _orig_root
store.reset_file_versions()
print("  Cleaned up")
print("  PASS")

print(f"\n{SEP}")
print("ALL 10 STEPS PASSED")
print(SEP)
