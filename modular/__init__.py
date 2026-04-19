"""
modular/ — little-coder feature-module ecosystem
================================================

Each subdirectory is a self-contained feature module that can be
enabled, disabled, or removed without affecting the core REPL.

Module interface contract
-------------------------
Every module that wants to add slash-commands exposes a ``cmd.py``
with a ``COMMAND_DEFS`` dict:

    COMMAND_DEFS = {
        "mycommand": {
            "func":    my_cmd_func,          # (args, state, config) -> bool | tuple
            "help":    ("One-line desc", ["sub1", "sub2"]),  # for /help
            "aliases": ["mc"],               # optional
        }
    }

Every module that wants to add agent tools exposes ``TOOL_DEFS``
(list of ToolDef) in a ``tools.py`` file.

Discovery
---------
``load_all_commands()`` scans every subdirectory for a ``cmd.py``
with ``COMMAND_DEFS`` and merges them into one dict.

Adding a new module
-------------------
1. Create ``modular/<name>/`` with at least ``__init__.py`` and ``cmd.py``
2. It is auto-discovered — no registration needed in this file.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

_HERE = Path(__file__).parent


def _module_dirs() -> list[Path]:
    """Return subdirectories that look like feature modules."""
    return [
        d for d in sorted(_HERE.iterdir())
        if d.is_dir() and not d.name.startswith("_") and (d / "__init__.py").exists()
    ]


def load_all_commands() -> dict[str, dict]:
    """
    Scan all modular sub-packages for COMMAND_DEFS and return a merged dict.

    Returns:
        { "commandname": {"func": callable, "help": (desc, aliases), "aliases": []} }
    """
    result: dict[str, dict] = {}
    for mod_dir in _module_dirs():
        cmd_path = mod_dir / "cmd.py"
        if not cmd_path.exists():
            continue
        fqn = f"modular.{mod_dir.name}.cmd"
        try:
            mod = importlib.import_module(fqn)
            for cmd_name, cmd_def in getattr(mod, "COMMAND_DEFS", {}).items():
                if callable(cmd_def.get("func")):
                    result[cmd_name] = cmd_def
        except Exception as e:
            # Never crash the REPL because a module failed to import
            print(f"[modular] Warning: could not load {fqn}: {e}", file=sys.stderr)
    return result


def load_all_tools() -> list:
    """
    Scan all modular sub-packages for TOOL_DEFS and return a flat list.

    Each module exposes TOOL_DEFS (list[ToolDef]) in its tools.py.
    """
    result = []
    for mod_dir in _module_dirs():
        tools_path = mod_dir / "tools.py"
        if not tools_path.exists():
            continue
        fqn = f"modular.{mod_dir.name}.tools"
        try:
            mod = importlib.import_module(fqn)
            result.extend(getattr(mod, "TOOL_DEFS", []))
        except Exception as e:
            print(f"[modular] Warning: could not load {fqn}: {e}", file=sys.stderr)
    return result


def list_modules() -> list[dict]:
    """Return metadata for every discovered module (for /help or diagnostics)."""
    modules = []
    for mod_dir in _module_dirs():
        info: dict = {"name": mod_dir.name, "has_cmd": False, "has_tools": False}
        if (mod_dir / "cmd.py").exists():
            info["has_cmd"] = True
            fqn = f"modular.{mod_dir.name}.cmd"
            try:
                mod = importlib.import_module(fqn)
                info["commands"] = list(getattr(mod, "COMMAND_DEFS", {}).keys())
            except Exception:
                info["commands"] = []
        if (mod_dir / "tools.py").exists():
            info["has_tools"] = True
        # Try to read description from PLUGIN.md
        plugin_md = mod_dir / "PLUGIN.md"
        if plugin_md.exists():
            for line in plugin_md.read_text().splitlines():
                if line.startswith("description:"):
                    info["description"] = line.split(":", 1)[1].strip()
                    break
        modules.append(info)
    return modules
