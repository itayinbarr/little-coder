"""Memory file scanning with mtime tracking and freshness/age helpers.

Mirrors the key ideas from Claude Code's memoryScan.ts and memoryAge.ts:
  - Scan memory directories, sort newest-first
  - Format a manifest for display or AI relevance selection
  - Report memory age in human-readable form ("today", "3 days ago")
  - Emit a staleness caveat for memories older than 1 day
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path

from .store import get_memory_dir, parse_frontmatter, INDEX_FILENAME

MAX_MEMORY_FILES = 200


# ── Data model ─────────────────────────────────────────────────────────────

@dataclass
class MemoryHeader:
    """Lightweight descriptor loaded from a memory file's frontmatter.

    Attributes:
        filename:    basename of the .md file
        file_path:   absolute path
        mtime_s:     modification time (seconds since epoch)
        description: value from frontmatter `description:` field
        type:        value from frontmatter `type:` field
        scope:       "user" or "project"
    """
    filename: str
    file_path: str
    mtime_s: float
    description: str
    type: str
    scope: str


# ── Scanning ───────────────────────────────────────────────────────────────

def scan_memory_dir(mem_dir: Path, scope: str) -> list[MemoryHeader]:
    """Scan a single memory directory and return headers sorted newest-first.

    Reads only the frontmatter (first ~30 lines) for efficiency.
    Silently skips unreadable files. Caps at MAX_MEMORY_FILES entries.
    """
    if not mem_dir.is_dir():
        return []

    headers: list[MemoryHeader] = []
    for fp in mem_dir.glob("*.md"):
        if fp.name == INDEX_FILENAME:
            continue
        try:
            stat = fp.stat()
            # Read only the first 30 lines for frontmatter
            lines = fp.read_text(errors="replace").splitlines()[:30]
            snippet = "\n".join(lines)
            meta, _ = parse_frontmatter(snippet)
            headers.append(MemoryHeader(
                filename=fp.name,
                file_path=str(fp),
                mtime_s=stat.st_mtime,
                description=meta.get("description", ""),
                type=meta.get("type", ""),
                scope=scope,
            ))
        except Exception:
            continue

    headers.sort(key=lambda h: h.mtime_s, reverse=True)
    return headers[:MAX_MEMORY_FILES]


def scan_all_memories() -> list[MemoryHeader]:
    """Scan both user and project memory directories, merged newest-first."""
    user_dir = get_memory_dir("user")
    proj_dir = get_memory_dir("project")

    user_headers = scan_memory_dir(user_dir, "user")
    proj_headers = scan_memory_dir(proj_dir, "project")

    combined = user_headers + proj_headers
    combined.sort(key=lambda h: h.mtime_s, reverse=True)
    return combined[:MAX_MEMORY_FILES]


# ── Age / freshness ────────────────────────────────────────────────────────

def memory_age_days(mtime_s: float) -> int:
    """Days since mtime_s (floor-rounded, clamped to 0 for future times)."""
    return max(0, math.floor((time.time() - mtime_s) / 86_400))


def memory_age_str(mtime_s: float) -> str:
    """Human-readable age: 'today', 'yesterday', or 'N days ago'."""
    d = memory_age_days(mtime_s)
    if d == 0:
        return "today"
    if d == 1:
        return "yesterday"
    return f"{d} days ago"


def memory_freshness_text(mtime_s: float) -> str:
    """Staleness caveat for memories older than 1 day (empty string if fresh).

    Motivated by user reports of stale code-state memories (file:line
    citations to code that has since changed) being asserted as fact.
    """
    d = memory_age_days(mtime_s)
    if d <= 1:
        return ""
    return (
        f"This memory is {d} days old. "
        "Memories are point-in-time observations, not live state — "
        "claims about code behavior or file:line citations may be outdated. "
        "Verify against current code before asserting as fact."
    )


# ── Manifest formatting ────────────────────────────────────────────────────

def format_memory_manifest(headers: list[MemoryHeader]) -> str:
    """Format a list of MemoryHeader as a text manifest.

    Format per line:  [type/scope] filename (age): description
    Example:
        [feedback/user] feedback_testing.md (3 days ago): Don't mock DB in tests
        [project/project] project_freeze.md (today): Merge freeze until 2026-04-10
    """
    lines = []
    for h in headers:
        tag = f"[{h.type}/{h.scope}]" if h.type else f"[{h.scope}]"
        age = memory_age_str(h.mtime_s)
        if h.description:
            lines.append(f"- {tag} {h.filename} ({age}): {h.description}")
        else:
            lines.append(f"- {tag} {h.filename} ({age})")
    return "\n".join(lines)
