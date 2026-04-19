"""File-based memory storage with user-level and project-level scopes.

Storage layout:
  user scope    : ~/.little-coder/memory/<slug>.md
  project scope : .little-coder/memory/<slug>.md  (relative to cwd)

MEMORY.md in each directory is the index file — rebuilt automatically after
every save/delete. It is loaded into the system prompt to give Claude an
overview of available memories.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


# ── Paths ──────────────────────────────────────────────────────────────────

USER_MEMORY_DIR = Path.home() / ".little-coder" / "memory"
INDEX_FILENAME = "MEMORY.md"

# Maximum lines/bytes for the index file (mirrors Claude Code limits)
MAX_INDEX_LINES = 200
MAX_INDEX_BYTES = 25_000


def get_project_memory_dir() -> Path:
    """Return the project-local memory directory (relative to cwd)."""
    return Path.cwd() / ".little-coder" / "memory"


def get_memory_dir(scope: str = "user") -> Path:
    """Return the memory directory for the given scope.

    Args:
        scope: "user" (global ~/.little-coder/memory) or
               "project" (.little-coder/memory relative to cwd)
    """
    if scope == "project":
        return get_project_memory_dir()
    return USER_MEMORY_DIR


# ── Data model ─────────────────────────────────────────────────────────────

@dataclass
class MemoryEntry:
    """A single memory entry loaded from a .md file.

    Attributes:
        name:           human-readable name (also the display title in the index)
        description:    short one-line description (used for relevance decisions)
        type:           "user" | "feedback" | "project" | "reference"
        content:        body text of the memory
        file_path:      absolute path to the .md file on disk
        created:        date string, e.g. "2026-04-02"
        scope:          "user" | "project" — which directory this was loaded from
        confidence:     0.0–1.0 reliability score (default 1.0 = explicit user statement)
        source:         origin: "user" | "model" | "tool" | "consolidator"
        last_used_at:   ISO date of last retrieval (updated on MemorySearch hits)
        conflict_group: tag linking related/conflicting memories (e.g. "writing_style")
    """
    name: str
    description: str
    type: str
    content: str
    file_path: str = ""
    created: str = ""
    scope: str = "user"
    confidence: float = 1.0
    source: str = "user"
    last_used_at: str = ""
    conflict_group: str = ""


# ── Helpers ────────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    """Convert name to a filesystem-safe slug (max 60 chars)."""
    s = name.lower().strip().replace(" ", "_")
    s = re.sub(r"[^a-z0-9_]", "", s)
    return s[:60]


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse ---\\nkey: value\\n---\\nbody format.

    Returns:
        (meta_dict, body_str)
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()
    return meta, parts[2].strip()


def _format_entry_md(entry: MemoryEntry) -> str:
    """Render a MemoryEntry as a markdown file with YAML frontmatter."""
    lines = [
        "---",
        f"name: {entry.name}",
        f"description: {entry.description}",
        f"type: {entry.type}",
        f"created: {entry.created}",
    ]
    if entry.confidence != 1.0:
        lines.append(f"confidence: {entry.confidence:.2f}")
    if entry.source and entry.source != "user":
        lines.append(f"source: {entry.source}")
    if entry.last_used_at:
        lines.append(f"last_used_at: {entry.last_used_at}")
    if entry.conflict_group:
        lines.append(f"conflict_group: {entry.conflict_group}")
    lines.append("---")
    lines.append(entry.content)
    return "\n".join(lines) + "\n"


# ── Core storage operations ────────────────────────────────────────────────

def save_memory(entry: MemoryEntry, scope: str = "user") -> None:
    """Write/update a memory file and rebuild the index for that scope.

    If a memory with the same name (slug) already exists, it is overwritten.

    Args:
        entry: MemoryEntry to persist
        scope: "user" or "project"
    """
    mem_dir = get_memory_dir(scope)
    mem_dir.mkdir(parents=True, exist_ok=True)
    slug = _slugify(entry.name)
    fp = mem_dir / f"{slug}.md"
    fp.write_text(_format_entry_md(entry))
    entry.file_path = str(fp)
    entry.scope = scope
    _rewrite_index(scope)


def delete_memory(name: str, scope: str = "user") -> None:
    """Remove the memory file matching name and rebuild the index.

    No error if not found.
    """
    mem_dir = get_memory_dir(scope)
    slug = _slugify(name)
    fp = mem_dir / f"{slug}.md"
    if fp.exists():
        fp.unlink()
    _rewrite_index(scope)


def load_entries(scope: str = "user") -> list[MemoryEntry]:
    """Scan all .md files (except MEMORY.md) in a scope and return entries.

    Returns:
        List of MemoryEntry sorted alphabetically by name.
    """
    mem_dir = get_memory_dir(scope)
    if not mem_dir.exists():
        return []
    entries: list[MemoryEntry] = []
    for fp in sorted(mem_dir.glob("*.md")):
        if fp.name == INDEX_FILENAME:
            continue
        try:
            text = fp.read_text()
        except Exception:
            continue
        meta, body = parse_frontmatter(text)
        entries.append(MemoryEntry(
            name=meta.get("name", fp.stem),
            description=meta.get("description", ""),
            type=meta.get("type", "user"),
            content=body,
            file_path=str(fp),
            created=meta.get("created", ""),
            scope=scope,
            confidence=float(meta.get("confidence", 1.0)),
            source=meta.get("source", "user"),
            last_used_at=meta.get("last_used_at", ""),
            conflict_group=meta.get("conflict_group", ""),
        ))
    return entries


def load_index(scope: str = "all") -> list[MemoryEntry]:
    """Load memory entries from one or both scopes.

    Args:
        scope: "user", "project", or "all" (both combined)

    Returns:
        List of MemoryEntry (user entries first, then project).
    """
    if scope == "all":
        return load_entries("user") + load_entries("project")
    return load_entries(scope)


def search_memory(query: str, scope: str = "all") -> list[MemoryEntry]:
    """Case-insensitive keyword match on name + description + content.

    Returns:
        List of matching MemoryEntry objects.
    """
    q = query.lower()
    results = []
    for entry in load_index(scope):
        haystack = f"{entry.name} {entry.description} {entry.content}".lower()
        if q in haystack:
            results.append(entry)
    return results


def _rewrite_index(scope: str) -> None:
    """Rebuild MEMORY.md for the given scope from all .md files in that dir."""
    mem_dir = get_memory_dir(scope)
    if not mem_dir.exists():
        return
    index_path = mem_dir / INDEX_FILENAME
    entries = load_entries(scope)
    lines = [
        f"- [{e.name}]({Path(e.file_path).name}) — {e.description}"
        for e in entries
    ]
    index_path.write_text("\n".join(lines) + ("\n" if lines else ""))


def get_index_content(scope: str = "user") -> str:
    """Return raw MEMORY.md content for the given scope, or '' if absent."""
    mem_dir = get_memory_dir(scope)
    index_path = mem_dir / INDEX_FILENAME
    if not index_path.exists():
        return ""
    return index_path.read_text().strip()


def check_conflict(entry: "MemoryEntry", scope: str = "user") -> dict | None:
    """Check whether a same-named memory already exists with different content.

    Returns a dict with the existing memory's key fields if a conflict is found,
    or None if no existing file or if the content is identical.
    """
    mem_dir = get_memory_dir(scope)
    slug = _slugify(entry.name)
    fp = mem_dir / f"{slug}.md"
    if not fp.exists():
        return None
    try:
        meta, existing_content = parse_frontmatter(fp.read_text())
    except Exception:
        return None
    if existing_content.strip() == entry.content.strip():
        return None
    return {
        "existing_content": existing_content.strip(),
        "existing_confidence": float(meta.get("confidence", 1.0)),
        "existing_created": meta.get("created", ""),
        "existing_source": meta.get("source", "user"),
    }


def touch_last_used(file_path: str) -> None:
    """Update the last_used_at frontmatter field of a memory file to today.

    Called by MemorySearch when a memory is returned so staleness/utility
    tracking stays current. Silent on any error.
    """
    from datetime import date
    fp = Path(file_path)
    if not fp.exists():
        return
    try:
        text = fp.read_text()
        meta, body = parse_frontmatter(text)
        today = date.today().isoformat()
        if meta.get("last_used_at") == today:
            return  # already up to date, skip the write
        meta["last_used_at"] = today
        # Rebuild frontmatter
        fm_lines = ["---"]
        for k in ("name", "description", "type", "created", "confidence",
                   "source", "last_used_at", "conflict_group"):
            v = meta.get(k)
            if v is not None and str(v):
                fm_lines.append(f"{k}: {v}")
        fm_lines.append("---")
        new_text = "\n".join(fm_lines) + "\n" + body + "\n"
        fp.write_text(new_text)
    except Exception:
        pass
