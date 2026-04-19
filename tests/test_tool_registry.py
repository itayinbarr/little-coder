from __future__ import annotations

import pytest

from tool_registry import (
    ToolDef,
    clear_registry,
    execute_tool,
    get_all_tools,
    get_tool,
    get_tool_schemas,
    register_tool,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset registry before each test."""
    clear_registry()
    yield
    clear_registry()


def _make_echo_tool(name: str = "echo", read_only: bool = False) -> ToolDef:
    """Helper to build a simple echo tool."""
    schema = {
        "name": name,
        "description": f"Echo tool ({name})",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "text to echo"},
            },
            "required": ["text"],
        },
    }

    def func(params: dict, config: dict) -> str:
        return params["text"]

    return ToolDef(
        name=name,
        schema=schema,
        func=func,
        read_only=read_only,
        concurrent_safe=True,
    )


# ------------------------------------------------------------------
# register and get
# ------------------------------------------------------------------

def test_register_and_get():
    tool = _make_echo_tool()
    register_tool(tool)
    result = get_tool("echo")
    assert result is not None
    assert result.name == "echo"


def test_get_unknown_returns_none():
    assert get_tool("no_such_tool") is None


# ------------------------------------------------------------------
# get_all_tools
# ------------------------------------------------------------------

def test_get_all_tools_empty():
    assert get_all_tools() == []


def test_get_all_tools():
    register_tool(_make_echo_tool("a"))
    register_tool(_make_echo_tool("b"))
    names = [t.name for t in get_all_tools()]
    assert sorted(names) == ["a", "b"]


# ------------------------------------------------------------------
# get_tool_schemas
# ------------------------------------------------------------------

def test_get_tool_schemas():
    register_tool(_make_echo_tool("echo"))
    schemas = get_tool_schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "echo"


# ------------------------------------------------------------------
# execute_tool
# ------------------------------------------------------------------

def test_execute_tool():
    register_tool(_make_echo_tool())
    result = execute_tool("echo", {"text": "hello"}, config={})
    assert result == "hello"


def test_execute_unknown_tool():
    result = execute_tool("missing", {}, config={})
    assert "unknown" in result.lower() or "not found" in result.lower()


# ------------------------------------------------------------------
# output truncation
# ------------------------------------------------------------------

def test_output_truncation():
    def big_func(params: dict, config: dict) -> str:
        return "x" * 100

    tool = ToolDef(
        name="big",
        schema={"name": "big", "description": "big", "input_schema": {"type": "object", "properties": {}}},
        func=big_func,
        read_only=True,
        concurrent_safe=True,
    )
    register_tool(tool)

    result = execute_tool("big", {}, config={}, max_output=40)
    # first half = 20 chars, last quarter = 10 chars, marker in between
    assert len(result) < 100
    assert "truncated" in result
    # The kept portion: first 20 + last 10 should be present
    assert result.startswith("x" * 20)
    assert result.endswith("x" * 10)


def test_no_truncation_when_within_limit():
    register_tool(_make_echo_tool())
    result = execute_tool("echo", {"text": "short"}, config={})
    assert result == "short"


# ------------------------------------------------------------------
# duplicate register overwrites
# ------------------------------------------------------------------

def test_duplicate_register_overwrites():
    register_tool(_make_echo_tool("dup"))

    def new_func(params: dict, config: dict) -> str:
        return "new"

    replacement = ToolDef(
        name="dup",
        schema={"name": "dup", "description": "new", "input_schema": {"type": "object", "properties": {}}},
        func=new_func,
        read_only=False,
        concurrent_safe=False,
    )
    register_tool(replacement)

    assert len(get_all_tools()) == 1
    result = execute_tool("dup", {}, config={})
    assert result == "new"
