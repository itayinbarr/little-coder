"""MCP type definitions: server configs, tool descriptors, connection state."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Server config ─────────────────────────────────────────────────────────────

class MCPTransport(str, Enum):
    STDIO = "stdio"
    SSE   = "sse"
    HTTP  = "http"
    WS    = "ws"


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server.

    Mirrors the Claude Code schema (types.ts) for the two most useful transports.

    Stdio example:
        {"type": "stdio", "command": "uvx", "args": ["mcp-server-git"]}

    SSE/HTTP example:
        {"type": "sse", "url": "http://localhost:8080/sse",
         "headers": {"Authorization": "Bearer token"}}
    """
    name: str                                     # logical name in mcpServers dict
    transport: MCPTransport = MCPTransport.STDIO
    # stdio fields
    command: str = ""
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    # sse / http / ws fields
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    # optional
    timeout: int = 30                             # seconds per request
    disabled: bool = False

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "MCPServerConfig":
        transport_str = d.get("type", "stdio").lower()
        try:
            transport = MCPTransport(transport_str)
        except ValueError:
            transport = MCPTransport.STDIO
        return cls(
            name=name,
            transport=transport,
            command=d.get("command", ""),
            args=d.get("args", []),
            env=d.get("env", {}),
            url=d.get("url", ""),
            headers=d.get("headers", {}),
            timeout=int(d.get("timeout", 30)),
            disabled=bool(d.get("disabled", False)),
        )


# ── Connection state ──────────────────────────────────────────────────────────

class MCPServerState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING   = "connecting"
    CONNECTED    = "connected"
    ERROR        = "error"


# ── Tool descriptor ───────────────────────────────────────────────────────────

@dataclass
class MCPTool:
    """A tool provided by an MCP server, ready to register in tool_registry."""
    server_name: str
    tool_name: str                  # original name from server
    qualified_name: str             # mcp__<server>__<tool>
    description: str
    input_schema: Dict[str, Any]    # JSON Schema object
    read_only: bool = False         # from annotations.readOnlyHint

    def to_tool_schema(self) -> dict:
        """Convert to the schema format expected by the Claude API."""
        return {
            "name": self.qualified_name,
            "description": f"[MCP:{self.server_name}] {self.description}",
            "input_schema": self.input_schema or {"type": "object", "properties": {}},
        }


# ── JSON-RPC helpers ──────────────────────────────────────────────────────────

def make_request(method: str, params: Optional[dict], req_id: int) -> dict:
    msg: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def make_notification(method: str, params: Optional[dict] = None) -> dict:
    msg: dict = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    return msg


MCP_PROTOCOL_VERSION = "2024-11-05"

CLIENT_INFO = {
    "name": "little-coder",
    "version": "1.0.0",
}

INIT_PARAMS = {
    "protocolVersion": MCP_PROTOCOL_VERSION,
    "capabilities": {
        "tools": {},
        "roots": {"listChanged": False},
    },
    "clientInfo": CLIENT_INFO,
}
