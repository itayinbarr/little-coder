"""Skill-augmented tool system: select and inject relevant tool skills at runtime.

The idea: instead of the model guessing how to use tools from memory,
we inject compact skill guides into the prompt showing correct usage patterns.
This is critical for small models (2B-4B) that struggle with tool-call formatting.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from skill.loader import SkillDef, _parse_skill_file


# ── Tool skill registry ──────────────────────────────────────────────────

_tool_skills: dict[str, SkillDef] = {}
_skill_cache: dict[frozenset, str] = {}
_loaded = False


def _get_tool_skills_dir() -> Path:
    """Return the directory containing tool-guidance skill files."""
    # Look relative to this file's parent (the project root)
    return Path(__file__).parent.parent / "skill" / "tools"


def load_tool_skills() -> dict[str, SkillDef]:
    """Load tool-guidance skill files from skill/tools/*.md.

    Each file must have `type: tool-guidance` and `target_tool: ToolName`
    in its YAML frontmatter.  Indexed by target_tool name.
    """
    global _tool_skills, _loaded
    if _loaded:
        return _tool_skills

    skills_dir = _get_tool_skills_dir()
    if not skills_dir.is_dir():
        _loaded = True
        return _tool_skills

    for md_file in sorted(skills_dir.glob("*.md")):
        skill = _parse_skill_file(md_file, source="builtin")
        if skill is None:
            continue
        # Read target_tool from frontmatter
        try:
            text = md_file.read_text(encoding="utf-8")
            parts = text.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].strip().splitlines():
                    if line.strip().lower().startswith("target_tool"):
                        _, _, val = line.partition(":")
                        target = val.strip()
                        if target:
                            # Store token_cost as attribute
                            skill._token_cost = _extract_token_cost(parts[1])
                            _tool_skills[target] = skill
                            break
        except Exception:
            continue

    _loaded = True
    return _tool_skills


def _extract_token_cost(frontmatter: str) -> int:
    """Extract token_cost from frontmatter text."""
    for line in frontmatter.splitlines():
        if line.strip().lower().startswith("token_cost"):
            _, _, val = line.partition(":")
            try:
                return int(val.strip())
            except (ValueError, TypeError):
                pass
    return 150  # default


# ── Skill selection logic ─────────────────────────────────────────────────

# Intent keywords → likely tools
_INTENT_MAP: dict[str, list[str]] = {
    "read":       ["Read"],
    "show":       ["Read"],
    "view":       ["Read"],
    "cat":        ["Read"],
    "write":      ["Write"],
    "create":     ["Write", "Bash"],
    "implement":  ["Write", "Read"],
    "code":       ["Write", "Read"],
    "function":   ["Write", "Edit"],
    "class":      ["Write", "Edit"],
    "edit":       ["Edit"],
    "change":     ["Edit"],
    "modify":     ["Edit"],
    "fix":        ["Edit"],
    "update":     ["Edit"],
    "replace":    ["Edit"],
    "add":        ["Edit", "Write"],
    "refactor":   ["Edit", "Read"],
    "run":        ["Bash"],
    "execute":    ["Bash"],
    "install":    ["Bash"],
    "build":      ["Bash"],
    "test":       ["Bash"],
    "find":       ["Glob", "Grep"],
    "search":     ["Grep"],
    "grep":       ["Grep"],
    "glob":       ["Glob"],
    "fetch":      ["WebFetch"],
    "download":   ["WebFetch"],
    "url":        ["WebFetch"],
    "web":        ["WebSearch"],
    "agent":      ["Agent"],
    "delegate":   ["Agent"],
    "spawn":      ["Agent"],
}


def _find_last_failed_tool(messages: list) -> Optional[str]:
    """Find the name of the last tool that returned an error."""
    for msg in reversed(messages):
        if msg.get("role") == "tool":
            content = msg.get("content", "")
            if isinstance(content, str) and content.startswith("Error"):
                return msg.get("name", "")
    return None


def _get_recent_tools(messages: list, n: int = 2) -> list[str]:
    """Get tool names used in the last n assistant turns."""
    tools = []
    turns_seen = 0
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            turns_seen += 1
            if turns_seen > n:
                break
            for tc in msg.get("tool_calls", []):
                name = tc.get("name", "")
                if name and name not in tools:
                    tools.append(name)
    return tools


def _predict_tools(message: dict) -> list[str]:
    """Predict likely tools from the latest user message via keyword matching."""
    content = message.get("content", "") if isinstance(message, dict) else str(message)
    if not isinstance(content, str):
        return []
    words = set(content.lower().split())
    predicted = []
    for keyword, tool_names in _INTENT_MAP.items():
        if keyword in words:
            for tn in tool_names:
                if tn not in predicted:
                    predicted.append(tn)
    return predicted


def select_and_inject_skills(
    base_system: str,
    messages: list,
    tool_schemas: list,
    config: dict,
) -> str:
    """Select relevant tool skills and append to system prompt.

    Selection priority:
    1. Error recovery — last failed tool gets highest priority
    2. Recency — tools used in the last 2 turns
    3. Intent prediction — keyword matching on latest user message

    Respects a token budget (config["skill_token_budget"]).
    Returns the augmented system prompt.
    """
    budget = config.get("skill_token_budget", 500)
    if budget <= 0:
        return base_system

    skills = load_tool_skills()
    if not skills:
        return base_system

    selected: list[SkillDef] = []
    used_budget = 0

    def _try_add(tool_name: str) -> bool:
        nonlocal used_budget
        skill = skills.get(tool_name)
        if skill and skill not in selected:
            cost = getattr(skill, "_token_cost", 150)
            if used_budget + cost <= budget:
                selected.append(skill)
                used_budget += cost
                return True
        return False

    # 1. Error recovery (highest priority)
    failed = _find_last_failed_tool(messages)
    if failed:
        _try_add(failed)

    # 2. Recent tool usage
    for tool_name in _get_recent_tools(messages, n=2):
        if used_budget >= budget:
            break
        _try_add(tool_name)

    # 3. Intent-based prediction
    if messages and used_budget < budget:
        # Find last user message
        for msg in reversed(messages):
            if msg.get("role") == "user":
                predicted = _predict_tools(msg)
                for tool_name in predicted:
                    if used_budget >= budget:
                        break
                    _try_add(tool_name)
                break

    if not selected:
        return base_system

    # Check cache
    cache_key = frozenset(s.name for s in selected)
    if cache_key in _skill_cache:
        return base_system + _skill_cache[cache_key]

    # Build skill block
    skill_block = "\n\n## Tool Usage Guidance\n"
    for s in selected:
        # Get the target tool name from the skill
        target = ""
        for tname, tskill in skills.items():
            if tskill is s:
                target = tname
                break
        skill_block += f"\n### {target}\n{s.prompt}\n"

    _skill_cache[cache_key] = skill_block
    return base_system + skill_block


def clear_cache():
    """Clear the skill injection cache (useful for testing)."""
    global _skill_cache, _loaded, _tool_skills
    _skill_cache.clear()
    _tool_skills.clear()
    _loaded = False
