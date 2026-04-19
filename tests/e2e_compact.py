"""Tests for /compact command and compaction enhancements."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SEP = "=" * 60


@dataclass
class FakeState:
    messages: list = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    turn_count: int = 0


def test_compact():
    from compaction import (
        estimate_tokens, snip_old_tool_results, find_split_point,
        manual_compact,
    )

    # ── Step 1: estimate_tokens ──
    print(f"\n{SEP}")
    print("STEP 1: estimate_tokens")
    print(SEP)
    msgs = [
        {"role": "user", "content": "hello world"},
        {"role": "assistant", "content": "hi there, how can I help?"},
    ]
    tokens = estimate_tokens(msgs)
    assert tokens > 0
    print(f"  {tokens} tokens estimated")
    print("  PASS")

    # ── Step 2: snip_old_tool_results ──
    print(f"\n{SEP}")
    print("STEP 2: snip_old_tool_results")
    print(SEP)
    long_tool = "x" * 5000
    msgs = [
        {"role": "user", "content": "do something"},
        {"role": "tool", "tool_call_id": "1", "name": "Read", "content": long_tool},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "next"},
        {"role": "assistant", "content": "ok"},
    ]
    snip_old_tool_results(msgs, max_chars=2000, preserve_last_n_turns=2)
    assert len(msgs[1]["content"]) < 5000
    assert "snipped" in msgs[1]["content"]
    print(f"  Tool content snipped to {len(msgs[1]['content'])} chars")
    print("  PASS")

    # ── Step 3: find_split_point ──
    print(f"\n{SEP}")
    print("STEP 3: find_split_point")
    print(SEP)
    msgs = [{"role": "user", "content": f"message {i} " * 100} for i in range(20)]
    split = find_split_point(msgs, keep_ratio=0.3)
    assert 0 < split < 20
    print(f"  Split at index {split} out of {len(msgs)} messages")
    print("  PASS")

    # ── Step 4: manual_compact — too few messages ──
    print(f"\n{SEP}")
    print("STEP 4: manual_compact — too few messages")
    print(SEP)
    state = FakeState(messages=[{"role": "user", "content": "hi"}])
    success, msg = manual_compact(state, {"model": "test"})
    assert not success
    assert "Not enough" in msg
    print(f"  {msg}")
    print("  PASS")

    # ── Step 8: manual_compact — with mocked LLM ──
    print(f"\n{SEP}")
    print("STEP 5: manual_compact — with mocked LLM summary")
    print(SEP)

    # Build a large conversation
    big_msgs = []
    for i in range(30):
        big_msgs.append({"role": "user", "content": f"Question {i}: " + "x" * 200})
        big_msgs.append({"role": "assistant", "content": f"Answer {i}: " + "y" * 200})
    state = FakeState(messages=big_msgs)
    config = {"model": "test", "permission_mode": "auto"}

    # Mock the LLM call in compact_messages
    import compaction
    import providers

    class FakeTextChunk:
        def __init__(self, text):
            self.text = text

    def fake_stream(**kwargs):
        yield FakeTextChunk("Summary: discussed 30 topics about x and y.")

    with patch.object(providers, "stream", fake_stream), \
         patch.object(providers, "TextChunk", FakeTextChunk):
        success, msg = manual_compact(state, config)

    assert success
    assert "Compacted" in msg
    # Should have summary + ack + recent messages
    assert len(state.messages) < 60
    assert state.messages[0]["content"].startswith("[Previous conversation summary]")
    print(f"  {msg}")
    print(f"  Messages reduced from 60 to {len(state.messages)}")
    print("  PASS")

    # ── Step 9: manual_compact with focus instructions ──
    print(f"\n{SEP}")
    print("STEP 6: Verify focus instructions reach the prompt")
    print(SEP)

    captured_prompts = []
    def capture_stream(**kwargs):
        msgs = kwargs.get("messages", [])
        if msgs:
            captured_prompts.append(msgs[0].get("content", ""))
        yield FakeTextChunk("Focused summary.")

    big_msgs2 = []
    for i in range(20):
        big_msgs2.append({"role": "user", "content": f"Q{i} " + "a" * 200})
        big_msgs2.append({"role": "assistant", "content": f"A{i} " + "b" * 200})
    state = FakeState(messages=big_msgs2)

    with patch.object(providers, "stream", capture_stream), \
         patch.object(providers, "TextChunk", FakeTextChunk):
        success, msg = manual_compact(state, config, focus="database migration")

    assert success
    assert any("database migration" in p for p in captured_prompts), \
        f"Focus not found in prompts: {captured_prompts}"
    print(f"  Focus instruction was included in summarization prompt")
    print("  PASS")

    # Cleanup
    import shutil
    shutil.rmtree(str(tmpdir), ignore_errors=True)

    print(f"\n{SEP}")
    print("ALL 9 STEPS PASSED")
    print(SEP)


if __name__ == "__main__":
    test_compact()
