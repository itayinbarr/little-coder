"""End-to-end test for /init, /export, /copy, /status commands."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SEP = "=" * 60


@dataclass
class FakeState:
    messages: list = field(default_factory=list)
    total_input_tokens: int = 500
    total_output_tokens: int = 300
    turn_count: int = 3


def test_commands():
    tmpdir = Path(tempfile.mkdtemp(prefix="cmd_e2e_"))
    orig_cwd = os.getcwd()
    os.chdir(str(tmpdir))

    try:
        _run_tests(tmpdir)
    finally:
        os.chdir(orig_cwd)
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def _run_tests(tmpdir):
    # Import after chdir so paths resolve correctly
    from little_coder import cmd_init, cmd_export, cmd_copy, cmd_status, info, err

    state = FakeState(messages=[
        {"role": "user", "content": "Write a hello world function"},
        {"role": "assistant", "content": "def hello():\n    print('Hello, World!')"},
        {"role": "user", "content": "Add docstring"},
        {"role": "assistant", "content": 'def hello():\n    """Say hello."""\n    print(\'Hello, World!\')'},
    ])
    config = {
        "model": "claude-sonnet-4-6",
        "permission_mode": "auto",
        "_session_id": "test123",
    }

    # ── Step 1: /init ──
    print(f"\n{SEP}")
    print("STEP 1: /init — create CLAUDE.md")
    print(SEP)
    assert not (tmpdir / "CLAUDE.md").exists()
    result = cmd_init("", state, config)
    assert result == True
    assert (tmpdir / "CLAUDE.md").exists()
    content = (tmpdir / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## Project Overview" in content
    assert tmpdir.name in content  # project name from dir
    print(f"  Created CLAUDE.md ({len(content)} chars)")
    print("  PASS")

    # ── Step 2: /init — already exists ──
    print(f"\n{SEP}")
    print("STEP 2: /init — refuses if CLAUDE.md exists")
    print(SEP)
    result = cmd_init("", state, config)
    assert result == True  # handled, but didn't overwrite
    # Content should be unchanged
    assert (tmpdir / "CLAUDE.md").read_text(encoding="utf-8") == content
    print("  Correctly refused to overwrite")
    print("  PASS")

    # ── Step 3: /export (markdown) ──
    print(f"\n{SEP}")
    print("STEP 3: /export — default markdown export")
    print(SEP)
    result = cmd_export("", state, config)
    assert result == True
    export_dir = tmpdir / ".little-coder" / "exports"
    exports = list(export_dir.glob("conversation_*.md"))
    assert len(exports) == 1
    md_content = exports[0].read_text(encoding="utf-8")
    assert "## User" in md_content
    assert "## Assistant" in md_content
    assert "hello world" in md_content.lower() or "Hello, World!" in md_content
    print(f"  Exported to {exports[0].name} ({len(md_content)} chars)")
    print("  PASS")

    # ── Step 4: /export (json) ──
    print(f"\n{SEP}")
    print("STEP 4: /export <file.json> — JSON export")
    print(SEP)
    json_path = str(tmpdir / "convo.json")
    result = cmd_export(json_path, state, config)
    assert result == True
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    assert len(data) == 4
    assert data[0]["role"] == "user"
    print(f"  Exported {len(data)} messages to JSON")
    print("  PASS")

    # ── Step 5: /export — empty conversation ──
    print(f"\n{SEP}")
    print("STEP 5: /export — empty conversation")
    print(SEP)
    empty_state = FakeState(messages=[])
    result = cmd_export("", empty_state, config)
    assert result == True  # handled gracefully
    print("  Handled empty conversation")
    print("  PASS")

    # ── Step 6: /copy ──
    print(f"\n{SEP}")
    print("STEP 6: /copy — copies last assistant response")
    print(SEP)
    # Mock clipboard to capture output
    captured = []
    import subprocess as sp

    class FakeProc:
        def communicate(self, data):
            captured.append(data)

    def fake_popen(cmd, **kwargs):
        return FakeProc()

    with patch("subprocess.Popen", fake_popen):
        result = cmd_copy("", state, config)
    assert result == True
    assert len(captured) == 1
    # Check the copied content contains the last assistant message
    copied_text = captured[0].decode("utf-16le") if sys.platform == "win32" else captured[0].decode("utf-8")
    assert "docstring" in copied_text or "Say hello" in copied_text
    print(f"  Copied {len(copied_text)} chars")
    print("  PASS")

    # ── Step 7: /copy — no assistant messages ──
    print(f"\n{SEP}")
    print("STEP 7: /copy — no assistant messages")
    print(SEP)
    user_only = FakeState(messages=[{"role": "user", "content": "hello"}])
    result = cmd_copy("", user_only, config)
    assert result == True
    print("  Handled gracefully")
    print("  PASS")

    # ── Step 8: /status ──
    print(f"\n{SEP}")
    print("STEP 8: /status — show session info")
    print(SEP)
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = cmd_status("", state, config)
    output = buf.getvalue()
    assert result == True
    assert "claude-sonnet-4-6" in output
    assert "auto" in output
    assert "test123" in output
    assert "3" in output  # turn count
    print(output.strip())
    print("  PASS")

    print(f"\n{SEP}")
    print("ALL 8 STEPS PASSED")
    print(SEP)


if __name__ == "__main__":
    test_commands()
