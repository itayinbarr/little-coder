"""Memory tool registrations: MemorySave, MemoryDelete, MemorySearch.

Importing this module registers the three tools into the central registry.
"""
from __future__ import annotations

from datetime import datetime

from tool_registry import ToolDef, register_tool
from .store import MemoryEntry, save_memory, delete_memory, load_index, check_conflict, touch_last_used
from .context import find_relevant_memories
from .scan import scan_all_memories, format_memory_manifest


# ── Tool implementations ───────────────────────────────────────────────────

def _memory_save(params: dict, config: dict) -> str:
    """Save or update a persistent memory entry, with conflict detection."""
    scope = params.get("scope", "user")
    entry = MemoryEntry(
        name=params["name"],
        description=params["description"],
        type=params["type"],
        content=params["content"],
        created=datetime.now().strftime("%Y-%m-%d"),
        confidence=float(params.get("confidence", 1.0)),
        source=params.get("source", "user"),
        conflict_group=params.get("conflict_group", ""),
    )

    conflict = check_conflict(entry, scope=scope)
    save_memory(entry, scope=scope)

    scope_label = "project" if scope == "project" else "user"
    msg = f"Memory saved: '{entry.name}' [{entry.type}/{scope_label}]"
    if entry.confidence < 1.0:
        msg += f" (confidence: {entry.confidence:.0%})"
    if conflict:
        msg += (
            f"\n⚠ Replaced conflicting memory"
            f" (was {conflict['existing_source']}-sourced, {conflict['existing_confidence']:.0%} confidence,"
            f" written {conflict['existing_created'] or 'unknown date'})."
            f" Old content: {conflict['existing_content'][:120]}"
            f"{'...' if len(conflict['existing_content']) > 120 else ''}"
        )
    return msg


def _memory_delete(params: dict, config: dict) -> str:
    """Delete a persistent memory entry by name."""
    name = params["name"]
    scope = params.get("scope", "user")
    delete_memory(name, scope=scope)
    return f"Memory deleted: '{name}' (scope: {scope})"


def _memory_search(params: dict, config: dict) -> str:
    """Search memories by keyword query with optional AI relevance filtering.

    Results are ranked by: confidence × recency (30-day exponential decay).
    """
    import math, time as _time
    query = params["query"]
    use_ai = params.get("use_ai", False)
    max_results = params.get("max_results", 5)

    results = find_relevant_memories(
        query, max_results=max_results * 3, use_ai=use_ai, config=config
    )

    if not results:
        return f"No memories found matching '{query}'."

    # Re-rank by confidence × recency score
    now = _time.time()
    for r in results:
        age_days = max(0, (now - r["mtime_s"]) / 86400)
        recency = math.exp(-age_days / 30)   # half-life ≈ 21 days
        r["_rank"] = r.get("confidence", 1.0) * recency
    results.sort(key=lambda r: r["_rank"], reverse=True)
    results = results[:max_results]

    # Touch last_used_at for returned memories
    for r in results:
        if r.get("file_path"):
            touch_last_used(r["file_path"])

    lines = [f"Found {len(results)} relevant memory/memories for '{query}':", ""]
    for r in results:
        freshness = f"  ⚠ {r['freshness_text']}" if r["freshness_text"] else ""
        conf = r.get("confidence", 1.0)
        src = r.get("source", "user")
        meta_tag = ""
        if conf < 1.0 or src != "user":
            meta_tag = f"  [conf:{conf:.0%} src:{src}]"
        lines.append(
            f"[{r['type']}/{r['scope']}] {r['name']}{meta_tag}\n"
            f"  {r['description']}\n"
            f"  {r['content'][:200]}{'...' if len(r['content']) > 200 else ''}"
            f"{freshness}"
        )
    return "\n\n".join(lines)


def _memory_list(params: dict, config: dict) -> str:
    """List all memory entries with type, scope, age, confidence, and description."""
    from .store import load_entries

    scope_filter = params.get("scope", "all")
    scopes = ["user", "project"] if scope_filter == "all" else [scope_filter]

    all_entries = []
    for s in scopes:
        all_entries.extend(load_entries(s))

    if not all_entries:
        return "No memories stored." if scope_filter == "all" else f"No {scope_filter} memories stored."

    lines = [f"{len(all_entries)} memory/memories:"]
    for e in all_entries:
        conf_tag = f" conf:{e.confidence:.0%}" if e.confidence < 1.0 else ""
        src_tag = f" src:{e.source}" if e.source and e.source != "user" else ""
        cg_tag = f" grp:{e.conflict_group}" if e.conflict_group else ""
        meta = f"{conf_tag}{src_tag}{cg_tag}".strip()
        tag = f"[{e.type:9s}|{e.scope:7s}]"
        lines.append(f"  {tag} {e.name}{(' — ' + meta) if meta else ''}")
        if e.description:
            lines.append(f"    {e.description}")
    return "\n".join(lines)


# ── Tool registrations ─────────────────────────────────────────────────────

register_tool(ToolDef(
    name="MemorySave",
    schema={
        "name": "MemorySave",
        "description": (
            "Save a persistent memory entry as a markdown file with frontmatter. "
            "Use for information that should persist across conversations: "
            "user preferences, feedback/corrections, project context, or external references. "
            "Do NOT save: code patterns, architecture, git history, or task state.\n\n"
            "For feedback/project memories, structure content as: "
            "rule/fact, then **Why:** and **How to apply:** lines."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Human-readable name (becomes the filename slug)",
                },
                "type": {
                    "type": "string",
                    "enum": ["user", "feedback", "project", "reference"],
                    "description": (
                        "user=preferences/role, feedback=guidance on how to work, "
                        "project=ongoing work/decisions, reference=external system pointers"
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "Short one-line description (used for relevance decisions — be specific)",
                },
                "content": {
                    "type": "string",
                    "description": "Body text. For feedback/project: rule/fact + **Why:** + **How to apply:**",
                },
                "scope": {
                    "type": "string",
                    "enum": ["user", "project"],
                    "description": (
                        "'user' (default) = ~/.little-coder/memory/ shared across projects; "
                        "'project' = .little-coder/memory/ local to this project"
                    ),
                },
                "confidence": {
                    "type": "number",
                    "description": (
                        "Reliability score 0.0–1.0. Default 1.0 = explicit user statement. "
                        "Use ~0.8 for inferred preferences, ~0.6 for uncertain facts."
                    ),
                },
                "source": {
                    "type": "string",
                    "enum": ["user", "model", "tool"],
                    "description": (
                        "Origin of this memory: 'user' (default, explicit statement), "
                        "'model' (inferred by AI), 'tool' (from tool output)."
                    ),
                },
                "conflict_group": {
                    "type": "string",
                    "description": (
                        "Optional tag grouping related or potentially conflicting memories "
                        "(e.g. 'writing_style'). Helps with conflict resolution."
                    ),
                },
            },
            "required": ["name", "type", "description", "content"],
        },
    },
    func=_memory_save,
    read_only=False,
    concurrent_safe=False,
))

register_tool(ToolDef(
    name="MemoryDelete",
    schema={
        "name": "MemoryDelete",
        "description": "Delete a persistent memory entry by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the memory to delete"},
                "scope": {
                    "type": "string",
                    "enum": ["user", "project"],
                    "description": "Scope to delete from (default: 'user')",
                },
            },
            "required": ["name"],
        },
    },
    func=_memory_delete,
    read_only=False,
    concurrent_safe=False,
))

register_tool(ToolDef(
    name="MemorySearch",
    schema={
        "name": "MemorySearch",
        "description": (
            "Search persistent memories by keyword. Returns matching entries with "
            "content preview and staleness warning for old memories. "
            "Set use_ai=true to use AI-powered relevance ranking (costs a small API call)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 5)",
                },
                "use_ai": {
                    "type": "boolean",
                    "description": "Use AI relevance ranking (default: false = keyword only)",
                },
                "scope": {
                    "type": "string",
                    "enum": ["user", "project", "all"],
                    "description": "Which scope to search (default: 'all')",
                },
            },
            "required": ["query"],
        },
    },
    func=_memory_search,
    read_only=True,
    concurrent_safe=True,
))

register_tool(ToolDef(
    name="MemoryList",
    schema={
        "name": "MemoryList",
        "description": (
            "List all memory entries with type, scope, age, and description. "
            "Useful for reviewing what's been remembered before deciding to save or delete."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["user", "project", "all"],
                    "description": "Which scope to list (default: 'all')",
                },
            },
        },
    },
    func=_memory_list,
    read_only=True,
    concurrent_safe=True,
))
