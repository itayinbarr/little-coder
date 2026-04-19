"""Skill tool: lets the model invoke skills by name via tool call."""
from __future__ import annotations

from tool_registry import ToolDef, register_tool
from .loader import find_skill, load_skills, substitute_arguments


_SKILL_SCHEMA = {
    "name": "Skill",
    "description": (
        "Invoke a named skill (reusable prompt template). "
        "Use SkillList to see available skills and their triggers."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name (e.g. 'commit', 'review')",
            },
            "args": {
                "type": "string",
                "description": "Arguments to pass to the skill (replaces $ARGUMENTS)",
                "default": "",
            },
        },
        "required": ["name"],
    },
}

_SKILL_LIST_SCHEMA = {
    "name": "SkillList",
    "description": "List all available skills with their names, triggers, and descriptions.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


def _skill_tool(params: dict, config: dict) -> str:
    """Execute a skill by name and return its output."""
    skill_name = params.get("name", "").strip()
    args = params.get("args", "")

    # Look up by name first, then by trigger
    skill = None
    for s in load_skills():
        if s.name == skill_name:
            skill = s
            break
    if skill is None:
        skill = find_skill(skill_name)
    if skill is None:
        names = [s.name for s in load_skills()]
        return f"Error: skill '{skill_name}' not found. Available: {', '.join(names)}"

    rendered = substitute_arguments(skill.prompt, args, skill.arguments)
    message = f"[Skill: {skill.name}]\n\n{rendered}"

    # Run inline via agent and collect text output
    import agent as _agent
    system_prompt = config.get("_system_prompt", "")

    # Collect output text
    output_parts: list[str] = []
    sub_state = _agent.AgentState()
    sub_config = {**config, "_depth": config.get("_depth", 0) + 1}
    try:
        for event in _agent.run(message, sub_state, sub_config, system_prompt):
            if hasattr(event, "text"):
                output_parts.append(event.text)
    except Exception as e:
        return f"Skill execution error: {e}"

    return "".join(output_parts) or "(skill completed with no text output)"


def _skill_list_tool(params: dict, config: dict) -> str:
    skills = load_skills()
    if not skills:
        return "No skills available."
    lines = ["Available skills:\n"]
    for s in skills:
        triggers = ", ".join(s.triggers)
        hint = f"  args: {s.argument_hint}" if s.argument_hint else ""
        when = f"\n    when: {s.when_to_use}" if s.when_to_use else ""
        lines.append(f"- **{s.name}** [{triggers}]{hint}\n  {s.description}{when}")
    return "\n".join(lines)


def _register() -> None:
    register_tool(ToolDef(
        name="Skill",
        schema=_SKILL_SCHEMA,
        func=_skill_tool,
        read_only=False,
        concurrent_safe=False,
    ))
    register_tool(ToolDef(
        name="SkillList",
        schema=_SKILL_LIST_SCHEMA,
        func=_skill_list_tool,
        read_only=True,
        concurrent_safe=True,
    ))


_register()
