"""Register MCP tools into the central tool_registry.

Importing this module:
1. Loads .mcp.json config files
2. Connects to each configured MCP server
3. Discovers tools from each server
4. Registers each tool into tool_registry so Claude can use them

MCP tool qualified names follow the pattern:
    mcp__<server_name>__<tool_name>

This matches the Claude Code convention (mcp__serverName__toolName).
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional

from tool_registry import ToolDef, register_tool
from .client import MCPClient, MCPManager, get_mcp_manager
from .config import load_mcp_configs
from .types import MCPServerConfig, MCPTool


# ── Global state ──────────────────────────────────────────────────────────────

_initialized = False
_init_lock = threading.Lock()
_connect_errors: Dict[str, Optional[str]] = {}   # server → error or None


# ── Tool wrapper ──────────────────────────────────────────────────────────────

def _make_mcp_func(qualified_name: str):
    """Return a tool func that calls the MCP server for a given qualified name."""
    def _mcp_tool(params: dict, config: dict) -> str:
        mgr = get_mcp_manager()
        try:
            return mgr.call_tool(qualified_name, params)
        except Exception as e:
            return f"Error calling MCP tool '{qualified_name}': {e}"
    return _mcp_tool


def _register_tool(tool: MCPTool) -> None:
    td = ToolDef(
        name=tool.qualified_name,
        schema=tool.to_tool_schema(),
        func=_make_mcp_func(tool.qualified_name),
        read_only=tool.read_only,
        concurrent_safe=False,
    )
    register_tool(td)


# ── Initialization ────────────────────────────────────────────────────────────

def initialize_mcp(verbose: bool = False) -> Dict[str, Optional[str]]:
    """Load configs, connect servers, register tools. Idempotent.

    Returns a dict of {server_name: error_message_or_None}.
    """
    global _initialized, _connect_errors

    with _init_lock:
        if _initialized:
            return _connect_errors

        configs = load_mcp_configs()
        if not configs:
            _initialized = True
            return {}

        mgr = get_mcp_manager()
        for cfg in configs.values():
            mgr.add_server(cfg)

        errors = mgr.connect_all()
        _connect_errors = errors

        # Register tools from all successfully connected servers
        for client in mgr.list_servers():
            if client.state.value == "connected":
                for tool in client._tools:
                    _register_tool(tool)
                if verbose:
                    print(f"[MCP] {client.config.name}: {len(client._tools)} tool(s) registered")

        _initialized = True
        return errors


def reload_mcp() -> Dict[str, Optional[str]]:
    """Force a full reload: re-read configs, reconnect, re-register all tools."""
    global _initialized
    with _init_lock:
        _initialized = False
    return initialize_mcp()


def refresh_server(server_name: str) -> Optional[str]:
    """Reconnect a single server and re-register its tools. Returns error or None."""
    mgr = get_mcp_manager()
    client = next((c for c in mgr.list_servers() if c.config.name == server_name), None)
    if client is None:
        return f"Server '{server_name}' not configured"
    try:
        mgr.reload_server(server_name)
        for tool in client._tools:
            _register_tool(tool)
        return None
    except Exception as e:
        return str(e)


def get_connect_errors() -> Dict[str, Optional[str]]:
    return dict(_connect_errors)


# ── Auto-initialize on import ─────────────────────────────────────────────────
# Connect in a background thread so startup is not blocked.

def _background_init():
    try:
        initialize_mcp()
    except Exception:
        pass


_bg_thread = threading.Thread(target=_background_init, daemon=True)
_bg_thread.start()
