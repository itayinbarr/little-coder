"""Context window management for small models.

Small models (2B-4B params) typically have 4K-8K context windows.
This module provides aggressive pruning and compression to stay
within those limits while preserving the most relevant information.
"""
from __future__ import annotations

import re


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~3.5 chars per token."""
    return max(1, int(len(text) / 3.5))


def compress_system_prompt(
    full_prompt: str,
    budget_tokens: int,
) -> str:
    """Aggressively compress system prompt for small context windows.

    Strips verbose sections (examples, long explanations, hints)
    and truncates to budget.
    """
    if budget_tokens <= 0:
        return full_prompt

    current = estimate_tokens(full_prompt)
    if current <= budget_tokens:
        return full_prompt

    compressed = full_prompt

    # Remove sections that are least critical for tool use
    sections_to_strip = [
        # Remove platform hints (Windows instructions etc)
        (r"## Windows Shell Hints.*?(?=\n#|\Z)", ""),
        # Remove verbose multi-agent guidelines
        (r"## Multi-Agent Guidelines.*?(?=\n#|\Z)", ""),
        # Remove memory/CLAUDE.md section (injected separately)
        (r"# Memory / CLAUDE\.md.*?(?=\n# |\Z)", ""),
        # Remove plan mode instructions
        (r"# Plan Mode.*?(?=\n# |\Z)", ""),
        # Remove plugin section
        (r"## Plugins.*?(?=\n#|\Z)", ""),
        # Remove MCP section
        (r"## MCP.*?(?=\n#|\Z)", ""),
        # Remove task management details
        (r"## Task Management.*?(?=\n#|\Z)", ""),
        # Simplify tool descriptions to just names
        (r"- \*\*(\w+)\*\*: .+", r"- \1"),
    ]

    for pattern, replacement in sections_to_strip:
        compressed = re.sub(pattern, replacement, compressed, flags=re.DOTALL)
        if estimate_tokens(compressed) <= budget_tokens:
            return compressed.strip()

    # If still too long, hard truncate
    char_budget = int(budget_tokens * 3.5)
    if len(compressed) > char_budget:
        compressed = compressed[:char_budget]
        # Try to end at a sentence boundary
        last_period = compressed.rfind(".")
        if last_period > char_budget * 0.8:
            compressed = compressed[: last_period + 1]

    return compressed.strip()


def prune_messages(
    messages: list,
    context_limit: int,
    reserved_for_generation: int = 1024,
) -> list:
    """Aggressively prune message history for small context windows.

    Strategy: always keep system context (index 0) + last N messages.
    Fill remaining budget from middle messages (most recent first).
    """
    if not messages:
        return messages

    available = context_limit - reserved_for_generation
    if available <= 0:
        return messages[-2:] if len(messages) >= 2 else messages

    # Always keep last 4 messages (current exchange + recent context)
    keep_tail = min(4, len(messages))
    tail = messages[-keep_tail:]

    tail_tokens = sum(estimate_tokens(_msg_text(m)) for m in tail)
    if tail_tokens >= available:
        # Even the tail is too big, keep only last 2
        return messages[-2:]

    if len(messages) <= keep_tail:
        return messages

    # Try to add more messages from the beginning/middle
    remaining_budget = available - tail_tokens
    head: list = []

    # Walk from the start, adding messages while budget allows
    for msg in messages[:-keep_tail]:
        msg_tokens = estimate_tokens(_msg_text(msg))
        if remaining_budget - msg_tokens < 0:
            break
        head.append(msg)
        remaining_budget -= msg_tokens

    if head:
        return head + tail

    return tail




def _msg_text(msg: dict) -> str:
    """Extract text content from a message dict."""
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                for v in block.values():
                    if isinstance(v, str):
                        parts.append(v)
        return " ".join(parts)
    return str(content)
