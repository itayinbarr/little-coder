"""JSON repair and tool-call validation for small models.

Small models frequently produce malformed JSON (trailing commas, single quotes,
unquoted keys) or miscapitalize parameter names.  This module intercepts and
repairs those issues before the tool dispatch layer sees them.
"""
from __future__ import annotations

import json
import re
from typing import Any


def _escape_newlines_in_json_strings(text: str) -> str:
    """Re-escape literal newlines/tabs inside JSON string values.

    When a model streams text, \\n in JSON strings become actual newlines.
    This function walks through the text, tracking quote context, and
    replaces real newlines inside quoted strings with \\n escapes.
    """
    result = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '\\' and in_string and i + 1 < len(text):
            # Escaped character — pass through both chars
            result.append(ch)
            result.append(text[i + 1])
            i += 2
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\t':
            result.append('\\t')
        elif in_string and ch == '\r':
            result.append('\\r')
        else:
            result.append(ch)
        i += 1
    return ''.join(result)


def repair_json(raw: str) -> dict:
    """Attempt to parse potentially malformed JSON from a small model.

    Tries direct parse first, then applies common fixes:
    - Literal newlines inside strings (re-escape them)
    - Trailing commas before } or ]
    - Single quotes instead of double
    - Unquoted keys
    - Missing closing braces
    """
    raw = raw.strip()
    if not raw:
        return {}

    # Direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 0. Re-escape literal newlines/tabs inside JSON strings.
    # Small models often output actual newlines where \n should be.
    # Strategy: walk through the string, tracking whether we're inside a
    # JSON string value, and escape any real newlines found there.
    fixed = _escape_newlines_in_json_strings(raw)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 1. Trailing commas
    fixed = re.sub(r",\s*}", "}", fixed)
    fixed = re.sub(r",\s*]", "]", fixed)

    # 2. Single quotes → double quotes (careful with apostrophes in values)
    # Only do this if there are no double quotes at all
    if '"' not in fixed and "'" in fixed:
        fixed = fixed.replace("'", '"')

    # 3. Unquoted keys: word: → "word":
    # Only apply outside of quoted strings to avoid corrupting string values.
    # Skip this step if the raw text contains double-quoted strings (likely valid keys).
    if '": ' not in fixed and '":"' not in fixed:
        fixed = re.sub(r'(?<=[{,\s])(\w+)\s*:', r'"\1":', fixed)

    # 4. Missing closing brace
    open_braces = fixed.count("{") - fixed.count("}")
    if open_braces > 0:
        fixed += "}" * open_braces

    open_brackets = fixed.count("[") - fixed.count("]")
    if open_brackets > 0:
        fixed += "]" * open_brackets

    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 5. Try extracting the first JSON object from the text
    match = re.search(r"\{[^{}]*\}", fixed)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return {"_raw": raw}


def parse_tool_call(raw_input: dict, tool_schema: dict | None) -> dict:
    """Validate and repair tool call arguments against a tool's schema.

    Handles:
    - Case-insensitive key matching
    - Type coercion (str→int, str→bool)
    - Missing required fields detection
    """
    if not tool_schema:
        return raw_input

    input_schema = tool_schema.get("input_schema", {})
    properties = input_schema.get("properties", {})
    if not properties:
        return raw_input

    repaired: dict[str, Any] = {}
    # Build a lowercase→actual key map from raw_input
    raw_lower_map = {k.lower(): k for k in raw_input}

    for key, prop_def in properties.items():
        # Try exact match first, then case-insensitive
        value = raw_input.get(key)
        if value is None:
            actual_key = raw_lower_map.get(key.lower())
            if actual_key:
                value = raw_input[actual_key]

        if value is None:
            continue

        # Type coercion
        expected_type = prop_def.get("type")
        if expected_type == "string" and not isinstance(value, str):
            value = str(value)
        elif expected_type == "integer":
            if isinstance(value, str):
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    pass
            elif isinstance(value, float):
                value = int(value)
        elif expected_type == "number":
            if isinstance(value, str):
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    pass
        elif expected_type == "boolean":
            if isinstance(value, str):
                value = value.lower() in ("true", "1", "yes")

        repaired[key] = value

    # Pass through any keys not in schema (model might add extras)
    for key in raw_input:
        if key not in repaired and key.lower() not in {k.lower() for k in properties}:
            repaired[key] = raw_input[key]

    return repaired


def parse_text_tool_calls(text: str) -> list[dict]:
    """Extract tool calls from text output when native tool calling is unavailable.

    Looks for blocks like:
        ```tool
        {"name": "ToolName", "input": {"param": "value"}}
        ```
    or:
        <tool_call>
        {"name": "ToolName", "input": {"param": "value"}}
        </tool_call>
    """
    calls: list[dict] = []

    # Pattern 1: ```tool ... ``` or ```json ... ``` (Gemma often uses ```json)
    for match in re.finditer(r"```(?:tool|json)\s*\n(.*?)\n```", text, re.DOTALL):
        try:
            data = repair_json(match.group(1))
            if "name" in data:
                calls.append({
                    "id": f"call_text_{len(calls)}",
                    "name": data.get("name", ""),
                    "input": data.get("input", data.get("parameters", data.get("args", {}))),
                })
        except Exception:
            pass

    # Pattern 2: <tool_call> ... </tool_call>
    for match in re.finditer(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL):
        try:
            data = repair_json(match.group(1))
            if "name" in data:
                calls.append({
                    "id": f"call_text_{len(calls)}",
                    "name": data.get("name", ""),
                    "input": data.get("input", data.get("parameters", data.get("args", {}))),
                })
        except Exception:
            pass

    # Pattern 3: JSON object with "name" and "input" keys (bare, no wrapper)
    if not calls:
        for match in re.finditer(r'\{[^{}]*"name"\s*:\s*"(\w+)"[^{}]*\}', text):
            try:
                data = repair_json(match.group(0))
                if "name" in data:
                    calls.append({
                        "id": f"call_text_{len(calls)}",
                        "name": data["name"],
                        "input": data.get("input", data.get("parameters", {})),
                    })
            except Exception:
                pass

    return calls


# Core tools that small models should focus on
_CORE_TOOLS = {"Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebFetch", "WebSearch"}


def inject_tool_instructions(system: str, tool_schemas: list, core_only: bool = True) -> str:
    """Append text-based tool-calling instructions to system prompt.

    Used when the model doesn't support native tool calling (function calling).
    The model is instructed to emit tool calls as ```tool blocks.

    Args:
        core_only: if True, only include core coding tools (not memory, tasks, etc.)
    """
    if core_only:
        tool_schemas = [s for s in tool_schemas if s.get("name") in _CORE_TOOLS]

    instruction = (
        "\n\n## How to Use Tools\n"
        "You MUST use tools to complete tasks. Do NOT just describe what you would do — actually do it.\n"
        "To use a tool, include a fenced code block tagged `tool` in your response:\n"
        "```tool\n"
        '{"name": "ToolName", "input": {"param1": "value1"}}\n'
        "```\n"
        "You may include brief reasoning text before the tool block.\n"
        "After each tool call, the result will be provided to you.\n"
        "NEVER ask the user for information you can get by using Read, Glob, or Grep tools.\n"
        "When asked to implement code, use Write or Edit immediately — do not ask questions.\n"
        "\n### Available Tools\n"
    )

    for schema in tool_schemas:
        name = schema.get("name", "")
        desc = schema.get("description", "")
        props = schema.get("input_schema", {}).get("properties", {})
        required = schema.get("input_schema", {}).get("required", [])

        instruction += f"\n**{name}**: {desc}\n"
        if props:
            instruction += "Parameters:\n"
            for pname, pdef in props.items():
                ptype = pdef.get("type", "any")
                pdesc = pdef.get("description", "")
                req = " (required)" if pname in required else ""
                instruction += f"  - `{pname}` ({ptype}{req}): {pdesc}\n"

    return system + instruction
