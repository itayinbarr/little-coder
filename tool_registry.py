"""Tool plugin registry for little-coder.

Provides a central registry for tool definitions, lookup, schema export,
and dispatch with output truncation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolDef:
    """Definition of a single tool plugin.

    Attributes:
        name: unique tool identifier
        schema: JSON-schema dict sent to the API (name, description, input_schema)
        func: callable(params: dict, config: dict) -> str
        read_only: True if the tool never mutates state
        concurrent_safe: True if safe to run in parallel with other tools
    """
    name: str
    schema: Dict[str, Any]
    func: Callable[[Dict[str, Any], Dict[str, Any]], str]
    read_only: bool = False
    concurrent_safe: bool = False


# --------------- internal state ---------------

_registry: Dict[str, ToolDef] = {}


# --------------- public API ---------------

def register_tool(tool_def: ToolDef) -> None:
    """Register a tool, overwriting any existing tool with the same name."""
    _registry[tool_def.name] = tool_def


def get_tool(name: str) -> Optional[ToolDef]:
    """Look up a tool by name. Returns None if not found."""
    return _registry.get(name)


def get_all_tools() -> List[ToolDef]:
    """Return all registered tools (insertion order)."""
    return list(_registry.values())


def get_tool_schemas() -> List[Dict[str, Any]]:
    """Return the schemas of all registered tools (for API tool parameter)."""
    return [t.schema for t in _registry.values()]


def execute_tool(
    name: str,
    params: Dict[str, Any],
    config: Dict[str, Any],
    max_output: int = 32000,
) -> str:
    """Dispatch a tool call by name.

    Args:
        name: tool name
        params: tool input parameters dict
        config: runtime configuration dict
        max_output: maximum allowed output length in characters

    Returns:
        Tool result string, possibly truncated.
    """
    tool = get_tool(name)
    if tool is None:
        return f"Error: tool '{name}' not found."

    # Validate and repair args for small models
    try:
        from local.config import is_small_model
        if is_small_model(config.get("model", "")):
            from local.output_parser import parse_tool_call
            params = parse_tool_call(params, tool.schema)
    except Exception:
        pass  # don't let validation errors block execution

    try:
        result = tool.func(params, config)
    except Exception as e:
        return f"Error executing {name}: {e}"

    if len(result) > max_output:
        first_half = max_output // 2
        last_quarter = max_output // 4
        truncated = len(result) - first_half - last_quarter
        result = (
            result[:first_half]
            + f"\n[... {truncated} chars truncated ...]\n"
            + result[-last_quarter:]
        )

    return result


def clear_registry() -> None:
    """Remove all registered tools. Intended for testing."""
    _registry.clear()
