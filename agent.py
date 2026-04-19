"""Core agent loop: neutral message format, multi-provider streaming.

Enhanced with local-model adaptations:
- Skill-augmented tool use (inject usage patterns into prompts)
- Response quality monitoring with retry
- Task decomposition for complex requests
- Context pruning for small context windows
- Text-based tool fallback for models without native tool calling
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Generator

from tool_registry import get_tool_schemas
from tools import execute_tool
import tools as _tools_init  # ensure built-in tools are registered on import
from providers import stream, AssistantTurn, TextChunk, ThinkingChunk, detect_provider
from compaction import maybe_compact
from local.config import is_small_model, get_model_profile
from local.skill_augment import select_and_inject_skills
from local.knowledge_augment import select_and_inject_knowledge
from local.quality import assess_response, build_correction_message
from local.context_manager import compress_system_prompt, prune_messages
from local.output_parser import parse_text_tool_calls

# ── Re-export event types (used by little_coder.py) ────────────────────────
__all__ = [
    "AgentState", "run",
    "TextChunk", "ThinkingChunk",
    "ToolStart", "ToolEnd", "TurnDone", "PermissionRequest",
]


@dataclass
class AgentState:
    """Mutable session state. messages use the neutral provider-independent format."""
    messages: list = field(default_factory=list)
    total_input_tokens:  int = 0
    total_output_tokens: int = 0
    turn_count: int = 0


@dataclass
class ToolStart:
    name:   str
    inputs: dict

@dataclass
class ToolEnd:
    name:      str
    result:    str
    permitted: bool = True

@dataclass
class TurnDone:
    input_tokens:  int
    output_tokens: int

@dataclass
class PermissionRequest:
    description: str
    granted: bool = False


# ── Agent loop ─────────────────────────────────────────────────────────────

def run(
    user_message: str,
    state: AgentState,
    config: dict,
    system_prompt: str,
    depth: int = 0,
    cancel_check=None,
) -> Generator:
    """
    Multi-turn agent loop (generator).
    Yields: TextChunk | ThinkingChunk | ToolStart | ToolEnd |
            PermissionRequest | TurnDone

    Args:
        depth: sub-agent nesting depth, 0 for top-level
        cancel_check: callable returning True to abort the loop early
    """
    # Append user turn in neutral format
    user_msg = {"role": "user", "content": user_message}
    # Attach pending image from /image command if present
    pending_img = config.pop("_pending_image", None)
    if pending_img:
        user_msg["images"] = [pending_img]
    state.messages.append(user_msg)

    # Inject runtime metadata into config so tools (e.g. Agent) can access it
    config = {**config, "_depth": depth, "_system_prompt": system_prompt}

    # ── Local-model adaptations ──────────────────────────────────────────
    model = config.get("model", "")
    _small = is_small_model(model)
    profile = get_model_profile(model) if _small else {}

    # Apply model profile defaults to config (don't override explicit settings)
    if _small:
        for key, val in profile.items():
            if key not in config:
                config[key] = val

    # Prepare effective system prompt
    effective_system = system_prompt

    # Compress system prompt for small models
    if _small and profile.get("system_prompt_budget"):
        effective_system = compress_system_prompt(
            effective_system, profile["system_prompt_budget"]
        )

    # Inject relevant tool skills
    if _small and profile.get("skill_token_budget", 0) > 0:
        effective_system = select_and_inject_skills(
            effective_system, state.messages, get_tool_schemas(), config,
        )

    # Inject relevant domain knowledge (algorithm/CS cheat sheets)
    if _small and profile.get("knowledge_token_budget", 0) > 0:
        effective_system, required_tools = select_and_inject_knowledge(
            effective_system, state.messages, config,
        )
        # If knowledge entries require specific tools (e.g. Read for reference
        # docs), force-inject those tool skills so the model knows how to use them
        if required_tools:
            from local.skill_augment import load_tool_skills
            tool_skills = load_tool_skills()
            for tool_name in required_tools:
                skill = tool_skills.get(tool_name)
                if skill and f"### {tool_name}" not in effective_system:
                    effective_system += f"\n\n## Tool Usage Guidance\n\n### {tool_name}\n{skill.prompt}\n"

    retries = 0
    max_retries = profile.get("max_retries", 0) if _small else 0

    while True:
        if cancel_check and cancel_check():
            return
        state.turn_count += 1
        assistant_turn: AssistantTurn | None = None

        # Compact context if approaching window limit
        maybe_compact(state, config)

        # Prune messages for small context windows
        if _small:
            ctx_limit = profile.get("context_limit", 8192)
            state.messages = prune_messages(state.messages, ctx_limit)

        # Stream from provider (auto-detected from model name)
        for event in stream(
            model=config["model"],
            system=effective_system,
            messages=state.messages,
            tool_schemas=get_tool_schemas(),
            config=config,
        ):
            if isinstance(event, (TextChunk, ThinkingChunk)):
                yield event
            elif isinstance(event, AssistantTurn):
                assistant_turn = event

        if assistant_turn is None:
            break

        # ── Text-based tool fallback for small models ────────────────────
        # If the model didn't use native tool calling but embedded tool calls
        # in text (```tool blocks), parse them out and clean the text
        if _small and not assistant_turn.tool_calls and assistant_turn.text:
            text_calls = parse_text_tool_calls(assistant_turn.text)
            if os.environ.get("LITTLE_CODER_DEBUG"):
                import sys
                print(f"\n[DEBUG] Text tool parse: found {len(text_calls)} calls, text len={len(assistant_turn.text)}", file=sys.stderr)
            if text_calls:
                assistant_turn.tool_calls = text_calls
                # Strip tool call blocks from text to keep context clean
                import re
                cleaned = re.sub(r"```(?:tool|json)\s*\n.*?\n```", "", assistant_turn.text, flags=re.DOTALL)
                cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", cleaned, flags=re.DOTALL)
                assistant_turn.text = cleaned.strip()

        # ── Quality check for small models ───────────────────────────────
        if _small and max_retries > 0:
            ok, reason = assess_response(
                assistant_turn.text,
                assistant_turn.tool_calls,
                state.messages,
            )
            if not ok and retries < max_retries:
                retries += 1
                correction = build_correction_message(reason)
                state.messages.append({
                    "role": "user",
                    "content": correction,
                })
                continue  # re-enter the stream loop
            # Reset retry counter on success
            retries = 0

        # Record assistant turn in neutral format
        state.messages.append({
            "role":       "assistant",
            "content":    assistant_turn.text,
            "tool_calls": assistant_turn.tool_calls,
        })

        state.total_input_tokens  += assistant_turn.in_tokens
        state.total_output_tokens += assistant_turn.out_tokens
        yield TurnDone(assistant_turn.in_tokens, assistant_turn.out_tokens)

        if not assistant_turn.tool_calls:
            break   # No tools → conversation turn complete

        # ── Execute tools ────────────────────────────────────────────────
        for tc in assistant_turn.tool_calls:
            yield ToolStart(tc["name"], tc["input"])

            # Permission gate
            permitted = _check_permission(tc, config)
            if not permitted:
                req = PermissionRequest(description=_permission_desc(tc))
                yield req
                permitted = req.granted

            if not permitted:
                result = "Denied: user rejected this operation"
            else:
                result = execute_tool(
                    tc["name"], tc["input"],
                    permission_mode="accept-all",  # already gate-checked above
                    config=config,
                )

            yield ToolEnd(tc["name"], result, permitted)

            # Append tool result in neutral format
            state.messages.append({
                "role":         "tool",
                "tool_call_id": tc["id"],
                "name":         tc["name"],
                "content":      result,
            })


# ── Helpers ───────────────────────────────────────────────────────────────

def _check_permission(tc: dict, config: dict) -> bool:
    """Return True if operation is auto-approved (no need to ask user)."""
    perm_mode = config.get("permission_mode", "auto")
    name = tc["name"]

    if perm_mode == "accept-all":
        return True
    if perm_mode == "manual":
        return False   # always ask

    # "auto" mode: only ask for writes and non-safe bash
    if name in ("Read", "Glob", "Grep", "WebFetch", "WebSearch"):
        return True
    if name == "Bash":
        from tools import _is_safe_bash
        return _is_safe_bash(tc["input"].get("command", ""))
    return False   # Write, Edit → ask


def _permission_desc(tc: dict) -> str:
    name = tc["name"]
    inp  = tc["input"]
    if name == "Bash":   return f"Run: {inp.get('command', '')}"
    if name == "Write":  return f"Write to: {inp.get('file_path', '')}"
    if name == "Edit":   return f"Edit: {inp.get('file_path', '')}"
    return f"{name}({list(inp.values())[:1]})"
