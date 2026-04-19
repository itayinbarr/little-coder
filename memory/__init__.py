"""Memory package for little-coder.

Provides persistent, file-based memory across conversations.

Storage layout:
  user scope    : ~/.little-coder/memory/<slug>.md   (shared across projects)
  project scope : .little-coder/memory/<slug>.md     (local to cwd)

The MEMORY.md index in each directory is auto-maintained and injected
into the system prompt so Claude has an overview of available memories.

Public API (backward-compatible with the old memory.py module):
  MemoryEntry      — dataclass for a single memory
  save_memory()    — write/update a memory file
  delete_memory()  — remove a memory file
  load_index()     — load all entries from one or both scopes
  search_memory()  — keyword search across entries
  get_memory_context() — MEMORY.md content for system prompt injection
"""
from .store import (  # noqa: F401
    MemoryEntry,
    save_memory,
    delete_memory,
    load_index,
    load_entries,
    search_memory,
    get_index_content,
    parse_frontmatter,
    USER_MEMORY_DIR,
    INDEX_FILENAME,
    MAX_INDEX_LINES,
    MAX_INDEX_BYTES,
)
from .scan import (  # noqa: F401
    MemoryHeader,
    scan_memory_dir,
    scan_all_memories,
    format_memory_manifest,
    memory_age_days,
    memory_age_str,
    memory_freshness_text,
)
from .context import (  # noqa: F401
    get_memory_context,
    find_relevant_memories,
    truncate_index_content,
)
from .types import (  # noqa: F401
    MEMORY_TYPES,
    MEMORY_TYPE_DESCRIPTIONS,
    MEMORY_SYSTEM_PROMPT,
    WHAT_NOT_TO_SAVE,
)
from .consolidator import consolidate_session  # noqa: F401

__all__ = [
    # store
    "MemoryEntry",
    "save_memory",
    "delete_memory",
    "load_index",
    "load_entries",
    "search_memory",
    "get_index_content",
    "parse_frontmatter",
    "USER_MEMORY_DIR",
    "INDEX_FILENAME",
    "MAX_INDEX_LINES",
    "MAX_INDEX_BYTES",
    # scan
    "MemoryHeader",
    "scan_memory_dir",
    "scan_all_memories",
    "format_memory_manifest",
    "memory_age_days",
    "memory_age_str",
    "memory_freshness_text",
    # context
    "get_memory_context",
    "find_relevant_memories",
    "truncate_index_content",
    # types
    "MEMORY_TYPES",
    "MEMORY_TYPE_DESCRIPTIONS",
    "MEMORY_SYSTEM_PROMPT",
    "WHAT_NOT_TO_SAVE",
    # consolidator
    "consolidate_session",
]
