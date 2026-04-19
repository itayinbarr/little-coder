"""
modular/base.py — Interface protocol for little-coder feature modules.

Every module under modular/ is a regular Python package.
This file documents the conventions modules should follow.
Implementing it is optional — the registry uses duck-typing.

Minimal module layout
---------------------
    modular/<name>/
    ├── __init__.py      public Python API  (check_deps, etc.)
    ├── cmd.py           COMMAND_DEFS       (slash-command handlers)
    ├── tools.py         TOOL_DEFS          (agent tool handlers)  [optional]
    └── PLUGIN.md        metadata + docs

cmd.py contract
---------------
    COMMAND_DEFS: dict[str, CommandDef]

    CommandDef = {
        "func":    Callable[[str, Any, dict], bool | tuple],
        "help":    tuple[str, list[str]],   # (description, [subcommands])
        "aliases": list[str],               # e.g. ["vid", "v"]
    }

    func signature: (args: str, state: Any, config: dict) -> bool | tuple
    - Return True  → command handled, stay in REPL
    - Return tuple → sentinel (e.g. ("__voice__", text)) passed to REPL loop

tools.py contract
-----------------
    TOOL_DEFS: list[ToolDef]   (ToolDef from tool_registry.py)

Dependency declaration (PLUGIN.md frontmatter)
----------------------------------------------
    dependencies: [package1, package2]

These are checked at startup. Missing deps degrade gracefully — the
module's commands are still registered but show a helpful message.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class HasCommandDefs(Protocol):
    """Protocol for cmd.py modules."""
    COMMAND_DEFS: dict[str, dict]


@runtime_checkable
class HasToolDefs(Protocol):
    """Protocol for tools.py modules."""
    TOOL_DEFS: list


# Convenience type alias (not enforced at runtime)
CommandFunc = Callable[[str, Any, dict], "bool | tuple"]
