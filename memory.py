"""Backward-compatibility shim — real implementation is in memory/ package."""
from memory.store import (  # noqa: F401
    MemoryEntry,
    save_memory,
    delete_memory,
    load_index,
    search_memory,
    get_index_content,
    parse_frontmatter,
)
from memory.context import get_memory_context  # noqa: F401
