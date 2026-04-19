"""Memory context building for system prompt injection.

Provides:
  get_memory_context()      — full context string for system prompt
  find_relevant_memories()  — keyword (+ optional AI) relevance filtering
  truncate_index_content()  — line + byte truncation with warning
"""
from __future__ import annotations

from pathlib import Path

from .store import (
    USER_MEMORY_DIR,
    INDEX_FILENAME,
    MAX_INDEX_LINES,
    MAX_INDEX_BYTES,
    get_memory_dir,
    get_index_content,
    load_entries,
    search_memory,
)
from .scan import scan_all_memories, format_memory_manifest, memory_freshness_text
from .types import MEMORY_SYSTEM_PROMPT


# ── Index truncation ───────────────────────────────────────────────────────

def truncate_index_content(raw: str) -> str:
    """Truncate MEMORY.md content to line AND byte limits, appending a warning.

    Matches Claude Code's truncateEntrypointContent:
      - Line-truncates first (natural boundary)
      - Then byte-truncates at the last newline before the cap
      - Appends which limit fired
    """
    trimmed = raw.strip()
    content_lines = trimmed.split("\n")
    line_count = len(content_lines)
    byte_count = len(trimmed.encode())

    was_line_truncated = line_count > MAX_INDEX_LINES
    was_byte_truncated = byte_count > MAX_INDEX_BYTES

    if not was_line_truncated and not was_byte_truncated:
        return trimmed

    truncated = "\n".join(content_lines[:MAX_INDEX_LINES]) if was_line_truncated else trimmed

    if len(truncated.encode()) > MAX_INDEX_BYTES:
        # Cut at last newline before byte limit
        raw_bytes = truncated.encode()
        cut = raw_bytes[:MAX_INDEX_BYTES].rfind(b"\n")
        truncated = raw_bytes[: cut if cut > 0 else MAX_INDEX_BYTES].decode(errors="replace")

    if was_byte_truncated and not was_line_truncated:
        reason = f"{byte_count:,} bytes (limit: {MAX_INDEX_BYTES:,}) — index entries are too long"
    elif was_line_truncated and not was_byte_truncated:
        reason = f"{line_count} lines (limit: {MAX_INDEX_LINES})"
    else:
        reason = f"{line_count} lines and {byte_count:,} bytes"

    warning = (
        f"\n\n> WARNING: {INDEX_FILENAME} is {reason}. "
        "Only part of it was loaded. Keep index entries to one line under ~150 chars."
    )
    return truncated + warning


# ── System prompt context ──────────────────────────────────────────────────

def get_memory_context(include_guidance: bool = False) -> str:
    """Return memory context for injection into the system prompt.

    Combines user-level and project-level MEMORY.md content (if present).
    Returns empty string when no memories exist.

    Args:
        include_guidance: if True, prepend the full memory system guidance
                          (MEMORY_SYSTEM_PROMPT). Normally False since the
                          system prompt template already includes brief guidance.
    """
    parts: list[str] = []

    # User-level index
    user_content = get_index_content("user")
    if user_content:
        truncated = truncate_index_content(user_content)
        parts.append(truncated)

    # Project-level index (labelled separately)
    proj_content = get_index_content("project")
    if proj_content:
        truncated = truncate_index_content(proj_content)
        parts.append(f"[Project memories]\n{truncated}")

    if not parts:
        return ""

    body = "\n\n".join(parts)
    if include_guidance:
        return f"{MEMORY_SYSTEM_PROMPT}\n\n## MEMORY.md\n{body}"
    return body


# ── Relevant memory finder ─────────────────────────────────────────────────

def find_relevant_memories(
    query: str,
    max_results: int = 5,
    use_ai: bool = False,
    config: dict | None = None,
) -> list[dict]:
    """Find memories relevant to a query.

    Strategy:
      1. Always: keyword match on name + description + content
      2. If use_ai=True and config has a model: use a small AI call to rank

    Returns:
        List of dicts with keys: name, description, type, scope, content,
        file_path, mtime_s, freshness_text
    """
    # Step 1: Keyword filter
    keyword_results = search_memory(query)
    if not keyword_results:
        return []

    if not use_ai or not config:
        # Return top max_results by recency (newest first)
        from .scan import scan_all_memories
        headers = scan_all_memories()
        path_to_mtime = {h.file_path: h.mtime_s for h in headers}

        results = []
        for entry in keyword_results[:max_results * 3]:
            mtime_s = path_to_mtime.get(entry.file_path, 0)
            results.append({
                "name": entry.name,
                "description": entry.description,
                "type": entry.type,
                "scope": entry.scope,
                "content": entry.content,
                "file_path": entry.file_path,
                "mtime_s": mtime_s,
                "freshness_text": memory_freshness_text(mtime_s),
                "confidence": entry.confidence,
                "source": entry.source,
            })
        results.sort(key=lambda r: r["mtime_s"], reverse=True)
        return results[:max_results]

    # Step 2: AI-powered relevance selection (optional, lightweight)
    return _ai_select_memories(query, keyword_results, max_results, config)


def _ai_select_memories(
    query: str,
    candidates: list,
    max_results: int,
    config: dict,
) -> list[dict]:
    """Use a fast AI call to select the most relevant memories from candidates.

    Falls back to keyword results on any error.
    """
    try:
        from providers import stream, AssistantTurn
        from .scan import scan_all_memories

        headers = scan_all_memories()
        path_to_mtime = {h.file_path: h.mtime_s for h in headers}

        # Build manifest of candidates only
        manifest_lines = []
        for i, e in enumerate(candidates):
            manifest_lines.append(f"{i}: [{e.type}] {e.name} — {e.description}")
        manifest = "\n".join(manifest_lines)

        system = (
            "You select memories relevant to a query. "
            "Return a JSON object with key 'indices' containing a list of integer indices "
            f"(0-based) from the provided list. Select at most {max_results} entries. "
            "Only include indices clearly relevant to the query. Return {\"indices\": []} if none."
        )
        messages = [{"role": "user", "content": f"Query: {query}\n\nMemories:\n{manifest}"}]

        result_text = ""
        for event in stream(
            model=config.get("model", "claude-haiku-4-5-20251001"),
            system=system,
            messages=messages,
            tool_schemas=[],
            config={**config, "max_tokens": 256, "no_tools": True},
        ):
            if isinstance(event, AssistantTurn):
                result_text = event.text
                break

        import json as _json
        parsed = _json.loads(result_text)
        selected_indices = [int(i) for i in parsed.get("indices", []) if isinstance(i, int)]

    except Exception:
        # Fall back to keyword results
        selected_indices = list(range(min(max_results, len(candidates))))

    results = []
    for i in selected_indices[:max_results]:
        if i < 0 or i >= len(candidates):
            continue
        entry = candidates[i]
        mtime_s = path_to_mtime.get(entry.file_path, 0) if "path_to_mtime" in dir() else 0
        results.append({
            "name": entry.name,
            "description": entry.description,
            "type": entry.type,
            "scope": entry.scope,
            "content": entry.content,
            "file_path": entry.file_path,
            "mtime_s": mtime_s,
            "freshness_text": memory_freshness_text(mtime_s),
            "confidence": entry.confidence,
            "source": entry.source,
        })
    return results
