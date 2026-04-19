"""Response quality monitoring for small models.

Heuristic checks to catch common failure modes:
- Empty responses with no tool calls
- Repeated identical tool calls (infinite loop)
- Hallucinated / unknown tool names
- Malformed tool call arguments

Quality checks are cheap (no LLM calls) and run after every assistant turn.
"""
from __future__ import annotations

from tool_registry import get_tool


def assess_response(
    text: str,
    tool_calls: list[dict],
    messages: list[dict],
) -> tuple[bool, str]:
    """Heuristic quality check on an assistant response.

    Returns:
        (ok, reason) — True if response is acceptable, False + reason if not.
    """
    # 1. Empty response with no tool calls = likely failure
    if not text and not tool_calls:
        return False, "empty_response"

    # 2. Check for hallucinated tool names (only if registry is populated)
    from tool_registry import get_all_tools
    registry_populated = len(get_all_tools()) > 0
    for tc in tool_calls:
        name = tc.get("name", "")
        if not name:
            return False, "empty_tool_name"
        if registry_populated and get_tool(name) is None:
            return False, f"unknown_tool:{name}"

    # 3. Repeated tool call (same name + same args as previous turn)
    if tool_calls and len(messages) >= 2:
        prev_msg = None
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                prev_msg = msg
                break

        if prev_msg:
            prev_calls = prev_msg.get("tool_calls", [])
            for tc in tool_calls:
                for ptc in prev_calls:
                    if (tc.get("name") == ptc.get("name") and
                            tc.get("input") == ptc.get("input")):
                        return False, "repeated_tool_call"

    # 4. Tool call with empty/missing required inputs
    for tc in tool_calls:
        inp = tc.get("input", {})
        if isinstance(inp, dict) and inp.get("_raw"):
            return False, f"malformed_args:{tc.get('name', '?')}"

    return True, "ok"


def build_correction_message(reason: str) -> str:
    """Build a corrective user message based on the failure reason."""
    corrections = {
        "empty_response": (
            "Your previous response was empty. Please respond with either "
            "text or a tool call to make progress on the task."
        ),
        "empty_tool_name": (
            "Your tool call had an empty name. Please specify a valid tool name. "
            "Available tools include: Read, Write, Edit, Bash, Glob, Grep."
        ),
        "repeated_tool_call": (
            "You just made the exact same tool call as your previous turn. "
            "This suggests you may be stuck in a loop. Please try a different "
            "approach or explain what you're trying to accomplish."
        ),
    }

    if reason.startswith("unknown_tool:"):
        tool_name = reason.split(":", 1)[1]
        return (
            f"Tool '{tool_name}' does not exist. "
            "Available tools are: Read, Write, Edit, Bash, Glob, Grep, "
            "WebFetch, WebSearch, Agent. Please use one of these."
        )

    if reason.startswith("malformed_args:"):
        tool_name = reason.split(":", 1)[1]
        return (
            f"The arguments for tool '{tool_name}' were malformed (not valid JSON). "
            "Please provide the arguments as a proper JSON object."
        )

    return corrections.get(reason, f"Issue detected: {reason}. Please try again.")
