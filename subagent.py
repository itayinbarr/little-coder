"""Backward-compatibility shim — real implementation is in multi_agent/subagent.py."""
from multi_agent.subagent import (  # noqa: F401
    AgentDefinition,
    SubAgentTask,
    SubAgentManager,
    load_agent_definitions,
    get_agent_definition,
    _extract_final_text,
    _agent_run,
    _BUILTIN_AGENTS,
)
