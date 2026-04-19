"""mcp package — Model Context Protocol client for little-coder.

Usage
-----
MCP servers are configured in one of two JSON files:

  ~/.little-coder/mcp.json        (user-level, all projects)
  .mcp.json                      (project-level, current dir, overrides user)

Format:
    {
      "mcpServers": {
        "my-git-server": {
          "type": "stdio",
          "command": "uvx",
          "args": ["mcp-server-git"]
        },
        "my-remote": {
          "type": "sse",
          "url": "http://localhost:8080/sse"
        }
      }
    }

Supported transports:
  stdio  — spawn a local subprocess (most common)
  sse    — HTTP Server-Sent Events stream
  http   — plain HTTP POST (Streamable HTTP transport)

MCP tools are automatically discovered on startup and registered into the
tool_registry under the name  mcp__<server>__<tool>.
Claude can invoke them just like built-in tools.
"""
from .types import MCPServerConfig, MCPTool, MCPServerState, MCPTransport  # noqa: F401
from .client import MCPClient, MCPManager, get_mcp_manager                 # noqa: F401
from .config import (                                                       # noqa: F401
    load_mcp_configs,
    save_user_mcp_config,
    add_server_to_user_config,
    remove_server_from_user_config,
    list_config_files,
)
from .tools import initialize_mcp, reload_mcp, refresh_server              # noqa: F401
