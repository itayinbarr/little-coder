# Architecture Guide

This document is for developers who want to understand, modify, or extend **little-coder**.
For user-facing docs, see [README.md](../README.md). For the research narrative, see [whitepaper.md](whitepaper.md).

---

## Overview

little-coder is a Python CLI that lets LLMs (Ollama-local or cloud) operate as coding agents with tool use, skill injection, domain-knowledge injection, workspace awareness, persistent memory, sub-agents, MCP clients, plugins, and checkpoints. The codebase is a mix of top-level modules (REPL, agent loop, providers, tool registry, system-prompt builder) and focused sub-packages (memory, multi-agent, skill, mcp, plugin, task, checkpoint, modular).

```
User input
    │
    ▼
little_coder.py ── REPL, slash commands, rendering, startup banner
    │                (theme.py for colors, status_line.py for context footer)
    │
    ├──► agent.py  ── multi-turn loop, permission gates, quality gating
    │      │
    │      ├──► providers.py  ── streaming (Anthropic native / OpenAI-compat / Ollama)
    │      ├──► tool_registry.py  ── all tools register here
    │      ├──► compaction.py  ── context-window management
    │      │
    │      └──► local/  ── small-model preprocessing pipeline
    │             ├── skill_augment.py     tool-skill selection + injection
    │             ├── knowledge_augment.py domain-knowledge selection + injection
    │             ├── context_manager.py   prompt compression, message pruning
    │             ├── quality.py           empty/hallucinated/looped response detection
    │             ├── output_parser.py     text-based tool-call extraction + JSON repair
    │             ├── deliberate.py        parallel reasoning branches
    │             └── config.py            per-model profiles
    │
    ├──► context.py  ── system prompt builder (base + git + memory + CLAUDE.md
    │                                          + skill + knowledge + MCP + plugins)
    │
    ├──► Tool providers (each registers into tool_registry at import time):
    │      ├── tools.py           core: Read, Write, Edit, Bash, Glob, Grep, WebFetch,
    │      │                       WebSearch, NotebookEdit, GetDiagnostics, SleepTimer
    │      ├── memory/tools.py    MemorySave, MemoryDelete, MemorySearch, MemoryList
    │      ├── multi_agent/tools.py  Agent, CheckAgentResult, ListAgentTasks
    │      ├── skill/tools.py     Skill, SkillList
    │      ├── task/tools.py      TaskCreate, TaskUpdate, TaskGet, TaskList
    │      ├── mcp/tools.py       MCP server-provided tools (dynamic)
    │      └── plugin/loader.py   plugin-provided tools (dynamic)
    │
    ├──► Subsystems:
    │      ├── memory/       persistent file-based memory (index + per-entry markdown)
    │      ├── multi_agent/  threaded sub-agent manager
    │      ├── skill/        markdown skill loader + executor + built-in /commit, /review
    │      ├── mcp/          Model Context Protocol client (user + project config)
    │      ├── plugin/       plugin install/enable + recommendation engine
    │      ├── task/         task list with status lifecycle
    │      ├── checkpoint/   file-snapshot hooks + rewind
    │      └── modular/      feature modules (voice, video) with shared base protocol
    │
    ├──► workspace.py  ── detect_language, find_workspace_docs, read_exercise_spec
    │
    ├──► theme.py        ── color palette + Rich theme (lc.* style names)
    ├──► status_line.py  ── session projection + context footer rendering
    ├──► cloudsave.py    ── optional session sync via GitHub Gist
    └──► config.py       ── ~/.little-coder/config.json persistence
```

**Key invariants**:
- **Dependencies flow downward.** `local/*` consumes `skill/loader.py` output but does not import from `agent.py`. `multi_agent/subagent.py` uses a lazy import to call `agent.py`, avoiding a cycle.
- **Top-level `memory.py`, `subagent.py`, `skills.py` are backward-compat shims** that re-export from their respective packages (`memory/`, `multi_agent/`, `skill/`). New code should import from the packages directly.

---

## Module reference

### `tool_registry.py` — Tool plugin system

The central registry every tool registers into.

```python
@dataclass
class ToolDef:
    name: str               # unique identifier (e.g. "Read", "MemorySave")
    schema: dict            # JSON schema sent to the LLM API
    func: Callable          # (params: dict, config: dict) -> str
    read_only: bool         # True = auto-approve in 'auto' permission mode
    concurrent_safe: bool   # True = safe to run in parallel (for sub-agents)
```

Public API: `register_tool`, `get_tool(name)`, `get_all_tools()`, `get_tool_schemas()`, `execute_tool(name, params, config, max_output=32000)`, `clear_registry()`.

**Output truncation:** if a tool returns more than `max_output` chars, the result is truncated to `first_half + [... N chars truncated ...] + last_quarter`. Prevents a single tool call (e.g. reading a huge file) from blowing up the context window.

### `tools.py` — Core tool implementations

Eleven core tools: **Read, Write, Edit, Bash, Glob, Grep, WebFetch, WebSearch, NotebookEdit, GetDiagnostics, SleepTimer**. All register themselves via `tool_registry` at import time. Also installs the checkpoint hooks (`checkpoint.hooks.install_hooks()`) that snapshot files before any Write/Edit/NotebookEdit.

**Key invariants enforced at the tool level:**

1. **Write refuses on existing files.** `_write(file_path, content)` checks `Path(file_path).exists()` and returns a structured error including the exact `Edit` call-shape for the same path. The model physically cannot Write over an existing file — this is a runtime invariant, not skill-level guidance. Rationale and validation data in [`docs/benchmark-reproduction.md`](benchmark-reproduction.md).
2. **Edit failures return recovery guidance, not Write fallback.** The skill file explicitly directs the model to Read, fix `old_string`, and retry Edit. Combined with (1), Write is not a viable escape hatch.
3. **Permission gating** happens in `agent.py::_check_permission` before `tool_registry.execute_tool` is called. Read-only tools auto-approve in `auto` mode; mutating tools require permission.

Other internals: `_is_safe_bash(cmd)` whitelist, `generate_unified_diff`, `maybe_truncate_diff(diff_text, max_lines=80)`.

### `agent.py` — Core agent loop

`run()` is a generator that yields events as they happen.

```python
def run(user_message, state, config, system_prompt,
        depth=0, cancel_check=None) -> Generator:
```

**Loop logic:**

```
1. Append user message
2. Inject depth into config (for sub-agent depth tracking)
3. While True:
   a. cancel_check()                      — cooperative cancellation
   b. maybe_compact(state, config)        — compress if near context limit
   c. Stream from provider
      - TextChunk / ThinkingChunk events yielded as they come
      - If thinking budget exceeded: abort, reuse partial thinking
      - Parse native tool_calls, or extract from text (local/output_parser)
      - Quality check (local/quality)
   d. Record assistant message
   e. If no tool_calls → break
   f. For each tool_call:
      - Permission check (_check_permission)
      - Execute tool → ToolStart + ToolEnd events
      - Append tool result (including Write refusals, Edit errors)
   g. Loop (model sees tool results and responds)
```

**Event types:** `TextChunk`, `ThinkingChunk`, `ToolStart`, `ToolEnd`, `PermissionRequest`, `TurnDone`.

### `context.py` — System prompt builder

Assembles the system prompt in stages:

1. **Base template** — role, date, cwd, platform, tool schemas
2. **Git info** — branch, status, recent commits
3. **Memory** — `memory.get_memory_context()` produces the MEMORY.md index
4. **Project instructions** — CLAUDE.md / AGENTS.md (project + global)
5. **Skill injection** — `local/skill_augment.select_and_inject_skills()` appends `## Tool Usage Guidance` with 1–2 selected tool skills
6. **Knowledge injection** — `local/knowledge_augment.select_and_inject_knowledge()` appends `## Algorithm Reference` with 1–2 selected knowledge entries
7. **MCP context** — tool inventory from configured MCP servers, when any are connected
8. **Plugin context** — docs from enabled plugins

Stages 5 and 6 are gated on per-model token budgets in `local/config.py`. For qwen3.5: `skill_token_budget=300`, `knowledge_token_budget=200`. For smaller models (gemma3:4b): 100 / 100.

### `local/` — Small-model preprocessing pipeline

| Module | Responsibility |
|---|---|
| `skill_augment.py` | Loads `skill/tools/*.md` at startup. Selection priority: **error recovery** (failed tool's skill) → **recency** (tools used in last 2 turns) → **intent prediction** (keywords in user message → tools via `_INTENT_MAP`). Selected skills concatenate under `## Tool Usage Guidance`. Results cached by `frozenset(selected_names)`. |
| `knowledge_augment.py` | Loads `skill/knowledge/*.md` at startup. Scores `keywords` against user message (word=1.0, bigram=2.0). Entries with `score >= 2.0` are candidates; top entries within `knowledge_token_budget` selected. `requires_tools` declarations propagate back to `skill_augment`. Cached the same way. |
| `context_manager.py` | `estimate_tokens(text)` (len/3.5), `compress_system_prompt` (strips verbose sections in priority order), `prune_messages` (keeps last 4 + fills backwards), `snip_old_tool_results` (truncates tool-role messages older than `n` turns). |
| `quality.py` | Catches three failure modes: **empty response**, **hallucinated tool** (name not in registry), **loop** (same call with same args 3+ times). Agent loop decides whether to retry or surface. |
| `output_parser.py` | `extract_tool_calls(text)` and `repair_json(text)` for small models that emit malformed tool calls — fenced instead of native, trailing commas, truncation, split chunks. Fallback after native parsing fails. |
| `deliberate.py` | Parallel reasoning branches for deliberation-style prompting. |
| `config.py` | Per-model profiles (`MODEL_PROFILES`) overriding global defaults with context limits, thinking budgets, skill/knowledge budgets. |

### `compaction.py` — Context window management

Two layers:

- **Snip** (`snip_old_tool_results`) — rule-based, no API cost. Truncates tool-role messages older than `preserve_last_n_turns` (default 6). Keeps first half + last quarter.
- **Auto-compact** (`compact_messages`) — model-driven. Splits messages `[old | recent]` at ~70/30, calls the current model to summarize the old half, replaces old messages with `[summary + acknowledgment]`.

`maybe_compact()` triggers when `estimate_tokens(messages) > context_limit * 0.7`. Runs snip first, then auto-compact if still over.

### `memory/` — Persistent memory (package)

File-based memory stored in `~/.little-coder/memory/`.

| File | Role |
|---|---|
| `store.py` | CRUD operations (`save_memory`, `delete_memory`, `load_index`, `search_memory`, `get_index_content`, `parse_frontmatter`). |
| `scan.py` | Freshness/age helpers. Mirrors Claude Code's `memoryScan.ts` and `memoryAge.ts` patterns — newest-first sort, human-readable age, staleness caveat for memories > 1 day old. |
| `context.py` | `get_memory_context()` returns the MEMORY.md index text for injection into the system prompt. |
| `consolidator.py` | Session-end AI-driven extraction of long-term insights (user preferences, feedback corrections, project decisions) for promotion to persistent memory. Manual via `/memory consolidate`. |
| `tools.py` | Registers `MemorySave`, `MemoryDelete`, `MemorySearch`, `MemoryList`. |
| `types.py` | `MemoryEntry` dataclass. |

Memory files use markdown with YAML frontmatter (`name`, `description`, `type`, `created`). The top-level `memory.py` is a shim re-exporting from this package.

### `multi_agent/` — Threaded sub-agents (package)

Provides `AgentDefinition`, `SubAgentTask`, `SubAgentManager` via `multi_agent/subagent.py`, plus the `Agent` / `CheckAgentResult` / `ListAgentTasks` tools via `multi_agent/tools.py`.

**Design decisions:**

1. **Fresh context** — each sub-agent starts with empty message history + task prompt.
2. **Depth limiting** — `max_depth=3`, checked at spawn. Model gets an error (not silent tool removal) so it can adapt.
3. **Cooperative cancellation** — `cancel_check` callable checked each loop iteration. Python threads can't be killed safely, so we set a flag.
4. **Threading, not asyncio** — the codebase is synchronous generators. Threading via `concurrent.futures`.

The top-level `subagent.py` is a shim.

### `skill/` — Prompt templates + skill tools (package)

Skills are markdown files with YAML frontmatter. Not code — structured prompts that either get injected into the agent loop (tool skills, knowledge entries) or executed as slash commands.

| File | Role |
|---|---|
| `loader.py` | Parses frontmatter, discovers project-level (`./.little-coder/skills/`) + user-level (`~/.little-coder/skills/`) skills; project overrides user on name collision. |
| `executor.py` | Inline / fork execution: `execute_skill()` wraps the prompt as a user message and calls `agent.run()`. |
| `builtin.py` | Registers built-in slash skills: `/commit`, `/review`. |
| `tools.py` | Registers the `Skill` and `SkillList` tools for model-driven skill invocation. |
| `tools/*.md` | 8 tool-usage guidance files (one per core tool). Frontmatter: `target_tool`, `token_cost`, `priority`. |
| `knowledge/*.md` | 14 algorithm / domain cheat sheets. Frontmatter: `topic`, `keywords`, `token_cost`, optional `requires_tools`. |

The top-level `skills.py` is a shim.

### `mcp/` — Model Context Protocol client

MCP servers are configured via JSON: `~/.little-coder/mcp.json` (user) and `.mcp.json` (project, overrides user).

| File | Role |
|---|---|
| `config.py` | Parse + merge user/project configs. |
| `client.py` | MCP client connection lifecycle (stdio / SSE transports). |
| `tools.py` | Registers MCP server-provided tools into `tool_registry` at connect time. |
| `types.py` | Config and tool-definition types. |

MCP tools appear in the tool list alongside native tools and route through `tool_registry.execute_tool`. The system prompt's MCP context block lists connected servers + their provided tools.

### `plugin/` — Plugin system

Installable bundles of tools, skills, MCP configs, and commands. User-level install under `~/.little-coder/plugins/`.

| File | Role |
|---|---|
| `types.py` | `PluginManifest`, `PluginEntry`, `PluginScope`. |
| `store.py` | Install / uninstall / enable / disable / update / list. |
| `loader.py` | On startup: `load_all_plugins`, register plugin tools + skills + MCP configs into their respective registries. |
| `recommend.py` | Context-aware plugin recommendation engine — matches installed + marketplace entries against user messages and repo contents. |

Plugins can ship tools, skills, and MCP configs — all three are registered at load time into the same central registries native tools use. A plugin is indistinguishable from built-in functionality from the agent's perspective once loaded.

### `task/` — Task tracking

Session-scoped task list with pending/in_progress/completed/deleted status. Tools: `TaskCreate`, `TaskUpdate`, `TaskGet`, `TaskList`.

| File | Role |
|---|---|
| `types.py` | `Task`, `TaskStatus` dataclasses. |
| `store.py` | In-memory store with disk persistence; `create_task`, `get_task`, `list_tasks`, `update_task`, `delete_task`, `clear_all_tasks`, `reload_from_disk`. |
| `tools.py` | Registers the 4 Task tools. |

### `checkpoint/` — File snapshot system

Before any Write / Edit / NotebookEdit tool runs, a backup of the current file (or absence-of-file sentinel) is captured so the operation can be rewound.

| File | Role |
|---|---|
| `types.py` | `FileBackup`, `Snapshot`, `MAX_SNAPSHOTS`. |
| `store.py` | Snapshot storage + rewind logic. |
| `hooks.py` | `install_hooks()` wires the backup trigger into `tools.py` before mutating tools run. Called at `tools.py` import time. |

### `modular/` — Feature modules

Shared protocol for optional feature packages (`modular/voice/`, `modular/video/`). Each module follows the layout:

```
modular/<name>/
├── __init__.py      public Python API (check_deps, etc.)
├── cmd.py           COMMAND_DEFS (slash-command handlers)
├── tools.py         TOOL_DEFS (agent tool handlers) [optional]
└── PLUGIN.md        metadata + docs
```

Duck-typed; `modular/base.py` documents the conventions but doesn't enforce them.

### `workspace.py` — Workspace introspection

Utilities for probing a directory:

```python
detect_language(directory)     -> Optional[str]    # go / rust / cpp / js / java / python or None
find_workspace_docs(directory) -> list[Path]       # priority order
read_exercise_spec(directory)  -> str              # Exercism .docs/instructions.md + .append.md
```

`detect_language` fingerprints via build files (`go.mod`, `Cargo.toml`, `CMakeLists.txt`, `package.json` + `*.spec.js`, `build.gradle` + `gradlew`, `pyproject.toml` or `*_test.py`).

`find_workspace_docs` priority: `.docs/instructions.md` → `.docs/instructions.append.md` → `AGENTS.md` → `CLAUDE.md` → `SPEC.md` → `SPECIFICATION.md` → `README.md` → `docs/README.md`.

Available to any component; not wired into automatic session-start behavior — the workspace-discovery path goes through the `workspace_docs` knowledge entry which tells the model to call Glob + Read itself. Also used by `benchmarks/aider_polyglot.py` for pre-flight language detection.

### `providers.py` — Multi-provider abstraction

Two streaming adapters cover all providers:

| Adapter | Providers |
|---|---|
| `stream_anthropic()` | Anthropic (native SDK) |
| `stream_openai_compat()` | OpenAI, Gemini, Kimi, Qwen, Zhipu, DeepSeek, Ollama, LM Studio, Custom |

**Neutral message format** (provider-independent):

```python
{"role": "user", "content": "..."}
{"role": "assistant", "content": "...", "tool_calls": [{"id": "...", "name": "...", "input": {...}}]}
{"role": "tool", "tool_call_id": "...", "name": "...", "content": "..."}
```

Conversion: `messages_to_anthropic()`, `messages_to_openai()`, `tools_to_openai()`.

**Provider-specific handling:**
- **Ollama**: streaming thinking tokens via the `thinking` field (model-dependent), binary `think` on/off parameter. Passes `num_ctx` via `options` for known Ollama/LM Studio ports, and sets `keep_alive: -1` to prevent model unload during long tool executions.
- **Gemini 3**: `thought_signature` required in tool-call responses, captured transparently via `extra_content` on tool_call dicts.

### `theme.py` — Color palette + Rich theme

Single source of truth for visual identity. `COLORS` is a dict of hex values keyed by semantic name; `THEME` is a `rich.theme.Theme` mapping every `lc.*` style name to a concrete Style. Re-theming is a one-file edit. Falls back to `None` when Rich isn't installed.

Palette: violet `#7C3AED` primary, cyan `#00D9FF` accent for tool-call elements, slate `#6B7380` muted for metadata, spring green `#4ADE80` success, amber `#F59E0B` warning, rose `#F43F5E` error / red-zone.

### `status_line.py` — Session projection + context footer

Two responsibilities: compute context usage, project how many more user turns fit before a new session is recommended.

- `compute_session_projection(messages, ctx_limit) → dict` uses the same `chars / 4` token estimator as `compaction.estimate_tokens`. Average user-turn cost comes from the last 3 user messages (fallback 500 tokens). Assistant-turn tokens assumed ~2× user cost. Zones at 70% (`warn`) and 85% (`bad`) match `compaction.maybe_compact` triggers.
- `format_status_line(projection, model_name)` returns a renderable with zone-aware styling (`lc.status.ok` / `.warn` / `.bad`). Red zone appends a `/compact or /clear` hint.

Printed by `little_coder.py` immediately before every input prompt. Failures degrade silently to no status line.

### `cloudsave.py` — Session sync (optional)

Upload / list / download session archives to a GitHub Gist via a Personal Access Token. Not a core dependency — the agent runs fully offline without it.

### `config.py` — Configuration

Defaults in `~/.little-coder/config.json`:

| Key | Default | Description |
|---|---|---|
| `model` | `ollama/qwen3.5` | Active model |
| `max_tokens` | `4096` | Max output tokens |
| `permission_mode` | `auto` | Permission mode |
| `max_tool_output` | `32000` | Tool output truncation limit |
| `max_agent_depth` | `3` | Max sub-agent nesting |
| `max_concurrent_agents` | `3` | Thread pool size |

Per-model profiles in `local/config.py::MODEL_PROFILES` override these with model-specific context limits, thinking budgets, and skill/knowledge token budgets.

---

## Data flow example

User: *"Read config.py and change max_tokens to 16384"*

```
1. little_coder.py captures input, appends to message list
2. context.build_system_prompt(config) assembles:
   - base + git + memory index + CLAUDE.md
3. local/skill_augment selects tool skills:
   - intent prediction picks Read + Edit
   - injects read.md + edit.md under "## Tool Usage Guidance"
4. local/knowledge_augment scores knowledge files — no match, nothing injected
5. agent.run() streams the model response
6. Model emits: Read({file_path: "config.py"})
   - read_only → auto-approve
   - tool_registry.execute_tool("Read", ...) → file content (truncated if >32K)
7. Tool result appended, next API turn
8. Model emits: Edit({file_path: "config.py", old_string: "max_tokens = 8192",
                      new_string: "max_tokens = 16384"})
   - not read_only → permission request (or auto in accept-all mode)
   - checkpoint.hooks fires, snapshots config.py
   - _edit() runs, generates unified diff
9. little_coder.py renders the diff with ANSI red/green
10. Tool result appended, next turn
11. Model responds: "Done — changed max_tokens from 8192 to 16384"
12. No tool_calls → loop ends, TurnDone yielded
```

**On a "fix the bug in auth.py" request** where the model tries `Write({file_path: "auth.py", ...})` instead of Edit, `_write()` refuses with a structured error pointing at Edit. The model reads the error in the tool_result and typically recovers to Edit on its next turn. Observed recovery rate in the Aider Polyglot benchmark: near-universal — see `docs/benchmark-reproduction.md` § "Write-guard refusal".

---

## Testing

```bash
python -m pytest tests/ -v
```

Tests use `monkeypatch` and `tmp_path` fixtures to avoid side effects. Sub-agent tests mock `agent.run()` to avoid real API calls. Key files:

- `tests/test_tool_registry.py`, `tests/test_compaction.py`, `tests/test_memory.py`, `tests/test_subagent.py`
- `tests/test_skills.py`, `tests/test_skill_augment.py`, `tests/test_knowledge_augment.py`
- `tests/test_output_parser.py`, `tests/test_quality.py`, `tests/test_checkpoint.py`, `tests/test_plugin.py`, `tests/test_mcp.py`, `tests/test_task.py`
- `tests/test_diff_view.py`, `tests/test_context_manager.py`, `tests/test_config.py`
- `tests/e2e_checkpoint.py`, `tests/e2e_commands.py`, `tests/e2e_compact.py`

---

## Benchmark harness

- `benchmarks/aider_polyglot.py` — language-dispatching harness for the Aider Polyglot benchmark (Python, Go, Rust, JavaScript, C++, Java). Per-language specifics live in the harness, not the agent prompt: skip-marker strips (`xit→it`, `@Disabled`), named work dirs for cpp CMakeLists, `EXERCISM_RUN_ALL_TESTS` build flag, `cargo test --include-ignored`.
- `benchmarks/polyglot_status.py` — live status dashboard, safe to call during a running benchmark. Reads atomic-flushed JSON, prints per-language progress bars, rate, ETA, tool stats.
- `benchmarks/smoke_test_langs.sh` — reference-solution smoke test for each language's native test runner (no agent).
- `benchmarks/baseline_aider/` — scaffold-ablation baseline: vanilla Aider + Qwen3.5 on the same 225 exercises and context budget.

**Canonical result files:**
- `benchmarks/results_full_polyglot_run1.json` — little-coder run 1 (104/225 = 46.22%)
- `benchmarks/results_full_polyglot_run2.json` — little-coder run 2 (101/225 = 44.89%)
- `benchmarks/baseline_aider/tmp.benchmarks/` — vanilla Aider per-exercise results (43/225 = 19.11%)

Narratives: [`docs/benchmark-reproduction.md`](benchmark-reproduction.md) (run 1 vs run 2 reproduction), [`docs/benchmark-baseline-aider.md`](benchmark-baseline-aider.md) (scaffold ablation).
