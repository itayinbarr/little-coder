"""Skill execution: inline (current conversation) or forked (sub-agent)."""
from __future__ import annotations

from typing import Generator

from .loader import SkillDef, substitute_arguments


def execute_skill(
    skill: SkillDef,
    args: str,
    state,
    config: dict,
    system_prompt: str,
) -> Generator:
    """Execute a skill.

    If skill.context == "fork", runs as an isolated sub-agent and yields its events.
    Otherwise (inline), injects the rendered prompt into the current agent loop.

    Args:
        skill: SkillDef to execute
        args: raw argument string from user (after the trigger word)
        state: AgentState
        config: config dict (may contain _depth, model, etc.)
        system_prompt: current system prompt string
    Yields:
        agent events (TextChunk, ToolStart, ToolEnd, TurnDone, …)
    """
    rendered = substitute_arguments(skill.prompt, args, skill.arguments)
    message = f"[Skill: {skill.name}]\n\n{rendered}"

    if skill.context == "fork":
        yield from _execute_forked(skill, message, config, system_prompt)
    else:
        yield from _execute_inline(message, state, config, system_prompt)


def _execute_inline(message: str, state, config: dict, system_prompt: str) -> Generator:
    """Run skill prompt inline in the current conversation."""
    import agent as _agent
    yield from _agent.run(message, state, config, system_prompt)


def _execute_forked(
    skill: SkillDef,
    message: str,
    config: dict,
    system_prompt: str,
) -> Generator:
    """Run skill as an isolated sub-agent (separate conversation context)."""
    import agent as _agent

    # Build a sub-agent config with depth tracking
    depth = config.get("_depth", 0) + 1
    sub_config = {**config, "_depth": depth, "_system_prompt": system_prompt}
    if skill.model:
        sub_config["model"] = skill.model

    # Restrict tools if skill specifies allowed-tools
    if skill.tools:
        sub_config["_allowed_tools"] = skill.tools

    # Run in fresh state (no shared history)
    sub_state = _agent.AgentState()
    yield from _agent.run(message, sub_state, sub_config, system_prompt)
