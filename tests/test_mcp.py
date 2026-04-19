"""Tests for the MCP package (mcp/)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mcp.types import (
    MCPServerConfig, MCPTool, MCPServerState, MCPTransport,
    make_request, make_notification, INIT_PARAMS,
)
from mcp.config import load_mcp_configs, add_server_to_user_config, remove_server_from_user_config
from mcp.client import MCPManager, MCPClient, StdioTransport, get_mcp_manager
import mcp.config as _mcp_config


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_manager(monkeypatch):
    """Each test gets a fresh MCPManager singleton."""
    import mcp.client as _client_mod
    monkeypatch.setattr(_client_mod, "_manager", None)


@pytest.fixture()
def tmp_config(tmp_path, monkeypatch):
    """Redirect MCP config paths to tmp_path."""
    user_cfg = tmp_path / "mcp.json"
    monkeypatch.setattr(_mcp_config, "USER_MCP_CONFIG", user_cfg)
    monkeypatch.setattr(_mcp_config, "PROJECT_MCP_NAME", ".mcp_test.json")
    return tmp_path


# ── types ─────────────────────────────────────────────────────────────────────

class TestTypes:
    def test_server_config_from_dict_stdio(self):
        cfg = MCPServerConfig.from_dict("git", {
            "type": "stdio", "command": "uvx", "args": ["mcp-server-git"],
        })
        assert cfg.name == "git"
        assert cfg.transport == MCPTransport.STDIO
        assert cfg.command == "uvx"
        assert cfg.args == ["mcp-server-git"]

    def test_server_config_from_dict_sse(self):
        cfg = MCPServerConfig.from_dict("remote", {
            "type": "sse", "url": "http://localhost:8080/sse",
            "headers": {"Authorization": "Bearer tok"},
        })
        assert cfg.transport == MCPTransport.SSE
        assert cfg.url == "http://localhost:8080/sse"
        assert cfg.headers["Authorization"] == "Bearer tok"

    def test_server_config_defaults(self):
        cfg = MCPServerConfig.from_dict("x", {"command": "mybin"})
        assert cfg.transport == MCPTransport.STDIO   # default
        assert cfg.timeout == 30
        assert not cfg.disabled

    def test_server_config_disabled(self):
        cfg = MCPServerConfig.from_dict("x", {"command": "c", "disabled": True})
        assert cfg.disabled is True

    def test_mcp_tool_schema(self):
        tool = MCPTool(
            server_name="git",
            tool_name="git_status",
            qualified_name="mcp__git__git_status",
            description="Show git status",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        )
        schema = tool.to_tool_schema()
        assert schema["name"] == "mcp__git__git_status"
        assert "[MCP:git]" in schema["description"]
        assert "properties" in schema["input_schema"]

    def test_make_request(self):
        msg = make_request("tools/list", None, 1)
        assert msg["jsonrpc"] == "2.0"
        assert msg["id"] == 1
        assert msg["method"] == "tools/list"
        assert "params" not in msg

    def test_make_request_with_params(self):
        msg = make_request("tools/call", {"name": "x", "arguments": {}}, 2)
        assert msg["params"]["name"] == "x"

    def test_make_notification(self):
        msg = make_notification("notifications/initialized")
        assert msg["jsonrpc"] == "2.0"
        assert "id" not in msg
        assert msg["method"] == "notifications/initialized"

    def test_init_params_structure(self):
        assert "protocolVersion" in INIT_PARAMS
        assert "capabilities" in INIT_PARAMS
        assert "tools" in INIT_PARAMS["capabilities"]
        assert "clientInfo" in INIT_PARAMS


# ── config ────────────────────────────────────────────────────────────────────

class TestConfig:
    def test_load_empty(self, tmp_config):
        configs = load_mcp_configs()
        assert configs == {}

    def test_load_user_config(self, tmp_config):
        user_cfg = tmp_config / "mcp.json"
        user_cfg.write_text(json.dumps({
            "mcpServers": {
                "git": {"type": "stdio", "command": "uvx", "args": ["mcp-server-git"]}
            }
        }))
        configs = load_mcp_configs()
        assert "git" in configs
        assert configs["git"].command == "uvx"

    def test_load_project_config_overrides_user(self, tmp_config, monkeypatch):
        user_cfg = tmp_config / "mcp.json"
        user_cfg.write_text(json.dumps({
            "mcpServers": {"git": {"command": "old-cmd"}}
        }))
        # Write project config in cwd
        project_cfg = Path.cwd() / ".mcp_test.json"
        project_cfg.write_text(json.dumps({
            "mcpServers": {"git": {"command": "new-cmd"}}
        }))
        try:
            configs = load_mcp_configs()
            assert configs["git"].command == "new-cmd"
        finally:
            project_cfg.unlink(missing_ok=True)

    def test_add_server_to_user_config(self, tmp_config):
        add_server_to_user_config("my-server", {"type": "stdio", "command": "mybin"})
        user_cfg = tmp_config / "mcp.json"
        assert user_cfg.exists()
        data = json.loads(user_cfg.read_text())
        assert "my-server" in data["mcpServers"]
        assert data["mcpServers"]["my-server"]["command"] == "mybin"

    def test_remove_server_from_user_config(self, tmp_config):
        add_server_to_user_config("srv", {"command": "x"})
        removed = remove_server_from_user_config("srv")
        assert removed is True
        data = json.loads((tmp_config / "mcp.json").read_text())
        assert "srv" not in data["mcpServers"]

    def test_remove_nonexistent(self, tmp_config):
        assert remove_server_from_user_config("nonexistent") is False

    def test_multiple_servers(self, tmp_config):
        (tmp_config / "mcp.json").write_text(json.dumps({
            "mcpServers": {
                "a": {"command": "cmd_a"},
                "b": {"type": "sse", "url": "http://localhost/sse"},
            }
        }))
        configs = load_mcp_configs()
        assert len(configs) == 2
        assert configs["b"].transport == MCPTransport.SSE


# ── MCPClient (unit tests with mocked transport) ──────────────────────────────

class TestMCPClient:
    def _make_client(self, transport_mock):
        cfg = MCPServerConfig.from_dict("test", {"command": "dummy"})
        client = MCPClient(cfg)
        client._transport = transport_mock
        client.state = MCPServerState.CONNECTED
        client._capabilities = {"tools": {}}
        return client

    def test_list_tools_empty(self):
        t = MagicMock()
        t.request.return_value = {"tools": []}
        client = self._make_client(t)
        tools = client.list_tools()
        assert tools == []
        t.request.assert_called_once_with("tools/list", timeout=15)

    def test_list_tools_parses_tool(self):
        t = MagicMock()
        t.request.return_value = {"tools": [{
            "name": "git_status",
            "description": "Show git status",
            "inputSchema": {"type": "object", "properties": {}},
        }]}
        client = self._make_client(t)
        tools = client.list_tools()
        assert len(tools) == 1
        assert tools[0].tool_name == "git_status"
        assert tools[0].qualified_name == "mcp__test__git_status"
        assert tools[0].description == "Show git status"

    def test_list_tools_read_only_hint(self):
        t = MagicMock()
        t.request.return_value = {"tools": [{
            "name": "read_file",
            "description": "Read a file",
            "inputSchema": {},
            "annotations": {"readOnlyHint": True},
        }]}
        client = self._make_client(t)
        tools = client.list_tools()
        assert tools[0].read_only is True

    def test_list_tools_no_tools_capability(self):
        t = MagicMock()
        cfg = MCPServerConfig.from_dict("test", {"command": "dummy"})
        client = MCPClient(cfg)
        client._transport = t
        client.state = MCPServerState.CONNECTED
        client._capabilities = {}   # no "tools" key
        tools = client.list_tools()
        assert tools == []
        t.request.assert_not_called()

    def test_call_tool_success(self):
        t = MagicMock()
        t.request.return_value = {
            "content": [{"type": "text", "text": "hello from tool"}],
            "isError": False,
        }
        client = self._make_client(t)
        result = client.call_tool("git_status", {"path": "."})
        assert result == "hello from tool"

    def test_call_tool_error_flag(self):
        t = MagicMock()
        t.request.return_value = {
            "content": [{"type": "text", "text": "something went wrong"}],
            "isError": True,
        }
        client = self._make_client(t)
        result = client.call_tool("broken_tool", {})
        assert "[MCP tool error]" in result
        assert "something went wrong" in result

    def test_call_tool_image_content(self):
        t = MagicMock()
        t.request.return_value = {
            "content": [{"type": "image", "mimeType": "image/png"}],
            "isError": False,
        }
        client = self._make_client(t)
        result = client.call_tool("screenshot", {})
        assert "[image: image/png]" in result

    def test_call_tool_not_connected(self):
        cfg = MCPServerConfig.from_dict("test", {"command": "x"})
        client = MCPClient(cfg)
        client.state = MCPServerState.DISCONNECTED
        with pytest.raises(RuntimeError, match="not connected"):
            client.call_tool("tool", {})

    def test_qualified_name_sanitized(self):
        t = MagicMock()
        t.request.return_value = {"tools": [{
            "name": "my-tool.v2",
            "description": "A tool with special chars",
            "inputSchema": {},
        }]}
        client = self._make_client(t)
        tools = client.list_tools()
        # Dashes and dots should be replaced with underscores
        assert "-" not in tools[0].qualified_name
        assert "." not in tools[0].qualified_name

    def test_status_line_connected(self):
        t = MagicMock()
        t.request.return_value = {"tools": []}
        cfg = MCPServerConfig.from_dict("myserver", {"command": "x"})
        client = MCPClient(cfg)
        client._transport = t
        client.state = MCPServerState.CONNECTED
        client._capabilities = {"tools": {}}
        client._server_info = {"name": "My Server", "version": "1.0"}
        client._tools = []
        line = client.status_line()
        assert "myserver" in line
        assert "✓" in line

    def test_status_line_error(self):
        cfg = MCPServerConfig.from_dict("bad", {"command": "x"})
        client = MCPClient(cfg)
        client.state = MCPServerState.ERROR
        client._error = "connection refused"
        line = client.status_line()
        assert "✗" in line
        assert "connection refused" in line


# ── MCPManager ────────────────────────────────────────────────────────────────

class TestMCPManager:
    def test_add_server(self):
        mgr = MCPManager()
        cfg = MCPServerConfig.from_dict("srv", {"command": "x"})
        client = mgr.add_server(cfg)
        assert client.config.name == "srv"
        assert len(mgr.list_servers()) == 1

    def test_call_tool_unknown_server(self):
        mgr = MCPManager()
        with pytest.raises(RuntimeError, match="not configured"):
            mgr.call_tool("mcp__unknown__tool", {})

    def test_call_tool_invalid_name(self):
        mgr = MCPManager()
        with pytest.raises(ValueError, match="Invalid MCP tool name"):
            mgr.call_tool("bad_name", {})

    def test_all_tools_empty_when_disconnected(self):
        mgr = MCPManager()
        cfg = MCPServerConfig.from_dict("s", {"command": "x"})
        mgr.add_server(cfg)
        assert mgr.all_tools() == []

    def test_all_tools_from_connected_server(self):
        mgr = MCPManager()
        cfg = MCPServerConfig.from_dict("s", {"command": "x"})
        client = mgr.add_server(cfg)
        # Manually set up connected state
        client.state = MCPServerState.CONNECTED
        client._tools = [MCPTool("s", "my_tool", "mcp__s__my_tool", "desc", {})]
        tools = mgr.all_tools()
        assert len(tools) == 1
        assert tools[0].qualified_name == "mcp__s__my_tool"

    def test_singleton(self):
        mgr1 = get_mcp_manager()
        mgr2 = get_mcp_manager()
        assert mgr1 is mgr2


# ── StdioTransport (integration-style with echo) ──────────────────────────────

class TestStdioTransportEcho:
    """Use Python's own interpreter as a trivial echo MCP server."""

    ECHO_SERVER = """
import sys, json
# Handshake
line = sys.stdin.readline()
req = json.loads(line)
resp = {"jsonrpc": "2.0", "id": req["id"], "result": {"capabilities": {"tools": {}}, "serverInfo": {"name": "echo", "version": "0.1"}, "protocolVersion": "2024-11-05"}}
sys.stdout.write(json.dumps(resp) + "\\n")
sys.stdout.flush()
# tools/list
line = sys.stdin.readline()  # notifications/initialized (no response needed)
line = sys.stdin.readline()
req = json.loads(line)
resp = {"jsonrpc": "2.0", "id": req["id"], "result": {"tools": [{"name": "echo", "description": "echo tool", "inputSchema": {"type": "object", "properties": {"msg": {"type": "string"}}}}]}}
sys.stdout.write(json.dumps(resp) + "\\n")
sys.stdout.flush()
# tools/call
line = sys.stdin.readline()
req = json.loads(line)
resp = {"jsonrpc": "2.0", "id": req["id"], "result": {"content": [{"type": "text", "text": req["params"]["arguments"].get("msg", "hello")}], "isError": False}}
sys.stdout.write(json.dumps(resp) + "\\n")
sys.stdout.flush()
"""

    def test_full_round_trip(self, tmp_path):
        script = tmp_path / "echo_server.py"
        script.write_text(self.ECHO_SERVER)

        cfg = MCPServerConfig.from_dict("echo", {
            "type": "stdio",
            "command": "python3",
            "args": [str(script)],
            "timeout": 5,
        })
        client = MCPClient(cfg)
        client.connect()
        assert client.state == MCPServerState.CONNECTED

        tools = client.list_tools()
        assert len(tools) == 1
        assert tools[0].tool_name == "echo"

        result = client.call_tool("echo", {"msg": "hello world"})
        assert result == "hello world"

        client.disconnect()
        assert client.state == MCPServerState.DISCONNECTED
