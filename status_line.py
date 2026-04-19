"""Status line with context usage + message-until-new-session projection.

Shows in the REPL as a compact one-line footer that tells the user:

    Context: 12.4K/32K (38%) · ~18 msgs until recommended new session   model: ollama/qwen3.5

Color zones:
  - green   < 70%   plenty of headroom, normal session
  - yellow  70-85%  room is tight, consider compacting soon
  - red     > 85%   near the ceiling, /compact or /clear is recommended

The "msgs until" projection is computed from the average user-turn cost
over the last 3 user turns (with a 500-token fallback before we have
enough data). It's deliberately conservative early in a session so the
counter doesn't over-promise — better to see "~5 msgs left" and be
pleasantly surprised than "~100 left" and run out unexpectedly.

Integration: format_status_line() returns a Rich Text (or a plain str
when Rich is missing) that the REPL can print between turns. See
little_coder.py for how it's pinned above the input prompt.
"""
from __future__ import annotations

from typing import Optional

try:
    from rich.text import Text
    _RICH = True
except ImportError:
    _RICH = False
    Text = None   # type: ignore


# Thresholds for status-line zones. Matches compaction.maybe_compact's
# 70% trigger so the visual warning lines up with the mechanism that
# actually fires automatic compaction.
ZONE_YELLOW = 0.70
ZONE_RED    = 0.85

# Conservative fallback for avg user-turn cost before we have 3+ turns.
# Biases the projection toward "fewer messages remaining" early, which
# is the safe direction: better to be surprised by extra headroom than
# run out mid-turn.
_DEFAULT_AVG_USER_TOKENS = 500

# Observed ratio of assistant-turn tokens to user-turn tokens. Empirically
# the assistant's response (including tool calls + tool results) averages
# around 2x the user's prompt tokens. Tunable.
_ASSISTANT_RATIO = 2.0


def _estimate_message_tokens(msg: dict) -> int:
    """Rough token estimate for a single message. Mirrors compaction.py's
    chars/3.5 heuristic so the two modules agree on totals."""
    content = msg.get("content", "")
    if isinstance(content, list):
        # Anthropic-style content-block lists: sum the text blocks.
        text = ""
        for block in content:
            if isinstance(block, dict):
                text += block.get("text", "")
            elif isinstance(block, str):
                text += block
        content = text
    if not isinstance(content, str):
        content = str(content)
    return max(1, len(content) // 4)


def compute_session_projection(messages: list, ctx_limit: int) -> dict:
    """Compute context usage + a projection of messages remaining.

    Args:
        messages: full message history as the agent sees it
        ctx_limit: the model's effective context window (from
                   compaction.get_context_limit)

    Returns:
        {
          "tokens_used":            int,
          "tokens_limit":           int,
          "pct":                    float 0.0-1.0,
          "msgs_until_recommended": int,   # 0 if already at/over the limit
          "zone":                   "ok" | "warn" | "bad",
        }

    Zones use the 70% / 85% thresholds defined at module level.
    """
    if not ctx_limit or ctx_limit <= 0:
        return {
            "tokens_used": 0, "tokens_limit": 0, "pct": 0.0,
            "msgs_until_recommended": 0, "zone": "ok",
        }

    tokens_used = sum(_estimate_message_tokens(m) for m in messages)
    pct = min(1.0, tokens_used / ctx_limit)
    remaining = max(0, ctx_limit - tokens_used)

    # Average user-turn cost from the last 3 user messages. Fall back to
    # the default when the session is too young.
    user_msgs = [m for m in messages if m.get("role") == "user"]
    recent_user = user_msgs[-3:] if len(user_msgs) >= 3 else user_msgs
    if recent_user:
        avg_user = sum(_estimate_message_tokens(m) for m in recent_user) / len(recent_user)
    else:
        avg_user = _DEFAULT_AVG_USER_TOKENS
    avg_user = max(50, avg_user)   # floor so tiny prompts don't overstate remaining

    avg_turn = avg_user * (1.0 + _ASSISTANT_RATIO)
    msgs_until = int(remaining / avg_turn) if avg_turn > 0 else 0

    if pct >= ZONE_RED:
        zone = "bad"
    elif pct >= ZONE_YELLOW:
        zone = "warn"
    else:
        zone = "ok"

    return {
        "tokens_used": tokens_used,
        "tokens_limit": ctx_limit,
        "pct": pct,
        "msgs_until_recommended": max(0, msgs_until),
        "zone": zone,
    }


def _fmt_tokens(n: int) -> str:
    """Compact token count: 1234 → '1.2K', 34000 → '34K'."""
    if n < 1000:
        return str(n)
    if n < 10000:
        return f"{n/1000:.1f}K"
    return f"{n//1000}K"


def format_status_line(projection: dict, model_name: str = ""):
    """Return a Rich Text (or plain str when Rich is missing) ready to print.

    The returned object can go directly into console.print or print().
    """
    used   = projection["tokens_used"]
    limit  = projection["tokens_limit"]
    pct    = projection["pct"]
    msgs   = projection["msgs_until_recommended"]
    zone   = projection["zone"]

    zone_style = {
        "ok":   "lc.status.ok",
        "warn": "lc.status.warn",
        "bad":  "lc.status.bad",
    }.get(zone, "lc.status.ok")

    if limit <= 0:
        # Unknown context limit — still show model name if we have one.
        if _RICH:
            t = Text()
            t.append("Context: ", style="lc.muted")
            t.append("unknown", style="lc.muted")
            if model_name:
                t.append("   model: ", style="lc.muted")
                t.append(model_name, style="lc.accent")
            return t
        return f"Context: unknown" + (f"   model: {model_name}" if model_name else "")

    pct_str = f"{pct * 100:.0f}%"
    used_str = _fmt_tokens(used)
    limit_str = _fmt_tokens(limit)

    if zone == "bad":
        tail = f"  /compact or /clear"
    else:
        tail = ""

    if _RICH:
        t = Text()
        t.append("Context: ", style="lc.muted")
        t.append(f"{used_str}/{limit_str} ", style=zone_style)
        t.append(f"({pct_str}) ", style="lc.muted")
        t.append("· ", style="lc.muted")
        t.append(f"~{msgs} msgs until recommended new session", style=zone_style)
        if tail:
            t.append(tail, style="lc.warning")
        if model_name:
            t.append("   model: ", style="lc.muted")
            t.append(model_name, style="lc.accent")
        return t

    # Plain-ANSI fallback
    return (
        f"Context: {used_str}/{limit_str} ({pct_str}) · "
        f"~{msgs} msgs until recommended new session{tail}"
        + (f"   model: {model_name}" if model_name else "")
    )


def format_status_line_plain(projection: dict, model_name: str = "") -> str:
    """Plain-string variant for contexts that can't render Rich Text."""
    used = _fmt_tokens(projection["tokens_used"])
    limit = _fmt_tokens(projection["tokens_limit"])
    if projection["tokens_limit"] <= 0:
        return f"Context: unknown" + (f"   model: {model_name}" if model_name else "")
    pct = f"{projection['pct'] * 100:.0f}%"
    msgs = projection["msgs_until_recommended"]
    out = f"Context: {used}/{limit} ({pct}) · ~{msgs} msgs until recommended new session"
    if projection["zone"] == "bad":
        out += "  /compact or /clear"
    if model_name:
        out += f"   model: {model_name}"
    return out
