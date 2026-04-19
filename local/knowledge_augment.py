"""Domain-knowledge augmentation: inject relevant CS/algorithm cheat sheets at runtime.

Mirrors the tool-skill augmentation pattern (local/skill_augment.py) but for
domain knowledge — algorithm choice heuristics, data structure tradeoffs,
and pointers to bundled reference documentation.
This helps small models make better algorithmic decisions when solving coding problems.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from skill.loader import SkillDef, _parse_skill_file
from local.context_manager import estimate_tokens


# ── Knowledge entry registry ────────────────────────────────────────────────

_knowledge_entries: dict[str, SkillDef] = {}   # topic -> SkillDef
_entry_keywords: dict[str, list[str]] = {}      # topic -> keyword list
_entry_requires_tools: dict[str, list[str]] = {}  # topic -> required tool names
_knowledge_cache: dict[frozenset, str] = {}
_loaded = False


def _get_knowledge_dir() -> Path:
    """Return the directory containing domain-knowledge files."""
    return Path(__file__).parent.parent / "skill" / "knowledge"


def load_knowledge_entries() -> dict[str, SkillDef]:
    """Load domain-knowledge files from skill/knowledge/*.md.

    Each file must have `type: domain-knowledge` and `topic: <name>`
    in its YAML frontmatter.  Indexed by topic name.
    """
    global _knowledge_entries, _entry_keywords, _entry_requires_tools, _loaded
    if _loaded:
        return _knowledge_entries

    knowledge_dir = _get_knowledge_dir()
    if not knowledge_dir.is_dir():
        _loaded = True
        return _knowledge_entries

    for md_file in sorted(knowledge_dir.glob("*.md")):
        skill = _parse_skill_file(md_file, source="builtin")
        if skill is None:
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
            parts = text.split("---", 2)
            if len(parts) < 3:
                continue
            frontmatter = parts[1].strip()

            topic = ""
            keywords = []
            requires_tools = []
            token_cost = 150

            for line in frontmatter.splitlines():
                stripped = line.strip().lower()
                if stripped.startswith("topic"):
                    _, _, val = line.partition(":")
                    topic = val.strip()
                elif stripped.startswith("token_cost"):
                    _, _, val = line.partition(":")
                    try:
                        token_cost = int(val.strip())
                    except (ValueError, TypeError):
                        pass
                elif stripped.startswith("keywords"):
                    _, _, val = line.partition(":")
                    val = val.strip()
                    if val.startswith("[") and val.endswith("]"):
                        keywords = [
                            w.strip().strip("'\"")
                            for w in val[1:-1].split(",")
                            if w.strip()
                        ]
                elif stripped.startswith("requires_tools"):
                    _, _, val = line.partition(":")
                    val = val.strip()
                    if val.startswith("[") and val.endswith("]"):
                        requires_tools = [
                            w.strip().strip("'\"")
                            for w in val[1:-1].split(",")
                            if w.strip()
                        ]

            if topic and skill.prompt:
                # Enforce per-entry token cap
                if token_cost > 150:
                    token_cost = 150
                skill._token_cost = token_cost
                _knowledge_entries[topic] = skill
                _entry_keywords[topic] = keywords
                _entry_requires_tools[topic] = requires_tools
        except Exception:
            continue

    _loaded = True
    return _knowledge_entries


# ── Scoring and selection ────────────────────────────────────────────────────

def _score_entry(user_text: str, topic: str) -> float:
    """Score a knowledge entry's relevance to user text.

    Counts single-word keyword matches plus bigram phrase matches.
    Returns the score (higher = more relevant).
    """
    keywords = _entry_keywords.get(topic, [])
    if not keywords:
        return 0.0

    text_lower = user_text.lower()
    words = set(text_lower.split())
    score = 0.0

    for kw in keywords:
        if " " in kw:
            # Bigram/phrase match (e.g. "shortest path", "linked list")
            if kw in text_lower:
                score += 2.0  # phrases worth more
        else:
            if kw in words:
                score += 1.0

    return score


_MIN_SCORE_THRESHOLD = 2.0  # need at least 2 keyword matches


def select_and_inject_knowledge(
    base_system: str,
    messages: list,
    config: dict,
) -> tuple[str, list[str]]:
    """Select relevant knowledge entries and append to system prompt.

    Selection: score all entries against the first user message,
    pick top 1-2 within budget.

    Returns:
        (augmented_system_prompt, required_tool_names) — the second element
        lists any tool names that selected entries need (e.g. Read for
        reference docs), so the caller can ensure those tool skills are
        also injected.
    """
    budget = config.get("knowledge_token_budget", 0)
    if budget <= 0:
        return base_system, []

    # Skip for subtasks — they inherit parent context
    if config.get("_is_subtask", False):
        return base_system, []

    # Safety: don't inject if system prompt is already >40% of context
    context_limit = config.get("context_limit", 8192)
    if estimate_tokens(base_system) > context_limit * 0.4:
        return base_system, []

    entries = load_knowledge_entries()
    if not entries:
        return base_system, []

    # Find the first user message (the problem statement)
    user_text = ""
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                user_text = content
            break

    if not user_text:
        return base_system, []

    # Score all entries
    scored: list[tuple[float, str]] = []
    for topic in entries:
        score = _score_entry(user_text, topic)
        if score >= _MIN_SCORE_THRESHOLD:
            scored.append((score, topic))

    if not scored:
        return base_system, []

    # Sort by score descending, pick top entries within budget
    scored.sort(reverse=True)

    selected: list[tuple[str, SkillDef]] = []
    used_budget = 0

    for _score, topic in scored:
        entry = entries[topic]
        cost = getattr(entry, "_token_cost", 150)
        if used_budget + cost <= budget:
            selected.append((topic, entry))
            used_budget += cost

    if not selected:
        return base_system, []

    # Check cache
    cache_key = frozenset(topic for topic, _ in selected)
    if cache_key in _knowledge_cache:
        # Still collect required tools even from cache
        req_tools = []
        for topic, _ in selected:
            req_tools.extend(_entry_requires_tools.get(topic, []))
        return base_system + _knowledge_cache[cache_key], req_tools

    # Build knowledge block
    block = "\n\n## Algorithm Reference\n"
    for topic, entry in selected:
        block += f"\n### {topic}\n{entry.prompt}\n"

    # Collect required tool names from selected entries
    req_tools: list[str] = []
    for topic, _ in selected:
        for tool_name in _entry_requires_tools.get(topic, []):
            if tool_name not in req_tools:
                req_tools.append(tool_name)

    _knowledge_cache[cache_key] = block
    return base_system + block, req_tools


def clear_cache():
    """Clear the knowledge injection cache (useful for testing)."""
    global _knowledge_cache, _loaded, _knowledge_entries, _entry_keywords, _entry_requires_tools
    _knowledge_cache.clear()
    _knowledge_entries.clear()
    _entry_keywords.clear()
    _entry_requires_tools.clear()
    _loaded = False
