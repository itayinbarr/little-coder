# Changelog

All notable changes to little-coder are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and little-coder's public interface (CLI, providers, tools, skills) follows semver starting at `v0.0.1` post-rename.

## [v0.1.20] — 2026-04-26

### Changed — `AGENTS.md` deduplicated against pi's built-in system prompt
Inspecting `node_modules/@mariozechner/pi-coding-agent/dist/core/system-prompt.js:83-99` revealed that pi's built-in system prompt is always present at runtime, with `AGENTS.md` appended underneath as `# Project Context / ## AGENTS.md`. The two stack — they are not alternatives.

The v0.1.13-restored AGENTS.md (the full v0.0.5 SYSTEM_PROMPT_TEMPLATE revival) duplicated several things pi's base already covers, in different wording:

| pi's base says | v0.1.13 AGENTS.md *also* said |
|---|---|
| `Available tools: read / bash / edit / write` + benchmark schemas | A full "Available Tools" section listing Read / Write / Edit / Bash / ShellSession / Glob / Grep / WebFetch / WebSearch + Browser / Evidence |
| `Be concise in your responses` | "Be concise and direct. Lead with the answer." |
| `Show file paths clearly when working with files` | "Always use absolute paths for file operations." |

For small local models, redundant phrasings of the same rule act like distinct constraints — the model can over-fit to one wording or thrash between two. Empirically, the partial archived runs that used the *pre*-v0.1.13 simplified AGENTS.md trended higher on TB 2.0 (k=1: 36.84 % on 19/89 trials; k=5: 28.57 % on 104/445 trials) than the full-restore k=5 leaderboard run (23.82 % on 445/445). Sample sizes for the partial runs are noisy, but the direction is consistent enough to test on a like-for-like full 445-trial run.

This release rewrites `AGENTS.md` as a **delta over pi's base** rather than a re-implementation of it. Kept (little-coder-specific):

- Identity line (`You are little-coder, a coding agent specialized for small local language models.`)
- `# Capabilities & Autonomy` (autonomous-agent framing pi doesn't include)
- `# Runtime invariants` — Write-vs-Edit refusal invariant + Bash / ShellSession timeout guidance + benchmark-tool note (replaces the duplicative "Available Tools" section; keeps only the operational facts pi can't infer)
- `# Approaching complex tasks` and `# Handling ambiguity` (the deliberate-not-deliberation framing)
- `# Workspace discovery` (the spec-file/docs surface-once rule)
- `# Per-turn context augmentation` (load-bearing — explains the `## Tool Usage Guidance` and `## Algorithm Reference` injected blocks; pi cannot describe extensions it doesn't know about)
- `# Guidelines` — only items pi's base doesn't cover: prefer editing existing files, no unnecessary comments / docstrings / error handling, systematic multi-step work, conviction-not-deliberation + thinking-budget cap

Dropped (already covered by pi's base):

- The full Available Tools tool catalog (pi enumerates the available-tools section automatically with one-line snippets per tool)
- "Be concise and direct. Lead with the answer." (pi: `Be concise in your responses`)
- "Always use absolute paths for file operations." (pi: `Show file paths clearly`)
- "When reading files before editing, use line numbers to be precise." (pi: `Show file paths clearly` + the Read tool already returns line-numbered output)
- "If a task is unclear, ask for clarification before proceeding." (covered by the new `# Handling ambiguity` section)

Net length: ~50 lines (full v0.1.13 restore) → **~38 lines** (this dedup) → vs ~11 lines (pre-v0.1.13 simplified). The dedup keeps every behavioral nudge unique to little-coder while cutting redundant framing.

### Action: launching a full k=5 TB 2.0 run on the dedup'd prompt
A fresh `tb2-leaderboard-k5-*` run is launched against `terminal-bench@2.0` immediately after this commit. Result is the like-for-like comparator to the v0.1.18 submission (23.82 %, full v0.0.5 restore prompt) on the *same* dataset / model / scaffold / k. If the dedup wins, it becomes the going-forward default and the leaderboard submission is updated. If the v0.1.18 prompt wins on the full 445, the v0.0.5 restore is vindicated and stays.

No code, extension, or harness change in this release — only `AGENTS.md`. Tests unchanged.

## [v0.1.19] — 2026-04-26

### Updated — README to reflect the TB 2.0 leaderboard result
v0.1.18 recorded the submission in the changelog but left the README's benchmark table and Roadmap section still showing "in progress". This release fills both in:

- Benchmark table row (was `v0.1.9+ — in progress … Result —`) → now points to v0.1.13 (the prompt-fidelity release whose state actually produced the run, per `agent_info.version` in the trial `result.json` files), shows the **23.82 %** headline, and links to PR #158.
- Roadmap section item 3 (was "Terminal-Bench 2.0 — *in progress*") → now `done. 23.82 % … awaiting maintainer merge.`

No behavioral or code change. Tests unchanged.

## [v0.1.18] — 2026-04-26

### Submitted — Terminal-Bench 2.0 leaderboard, PR #158
The full k=5 run from `tb2-leaderboard-k5-2026-04-24__00-34-46` has been submitted to the Terminal-Bench 2.0 leaderboard as PR #158 on the official `harborframework/terminal-bench-2-leaderboard` HF dataset.

- **Result**: **23.82 %** (106 / 445) — Qwen3.6-35B-A3B via llama.cpp on a single RTX 5070 Laptop with 8 GB VRAM. No cloud inference. `timeout_multiplier=1.0`, no overrides.
- **PR**: https://huggingface.co/datasets/harborframework/terminal-bench-2-leaderboard/discussions/158
- **Status**: bot-validation passed; awaiting maintainer review/merge → auto-import to leaderboard at https://www.tbench.ai/leaderboard/terminal-bench/2.0.
- **Trials**: 89 tasks × 5 trials = 445 total; per-task uniformity verified, single `task_checksum` per task confirmed.
- **Errored trials**: 15 / 445 with `exception_info` populated (Docker compose image-pull timeouts, `AgentTimeoutError` at 1200/1800 s, `VerifierTimeoutError` at 900 s). All have valid `result.json`; counted as failed per the leaderboard's bot rules.
- **Submission package**: top-level `metadata.yaml` (`agent_url`, `agent_display_name="little-coder"`, `agent_org_display_name="Itay Inbar"`, model entry for `Qwen/Qwen3.6-35B-A3B` / provider `llamacpp`) + the run dir as the job-folder. The dataset's own `.gitignore` (`*.log`) auto-stripped per-trial agent/trial logs from the upload — `result.json` and `config.json` for every trial uploaded cleanly.
- **Agent version captured in trials**: `agent_info.version = "0.1.13"` — the version that was live when the run started (per the v0.1.13 prompt-fidelity restart noted earlier). The submission represents the v0.1.13 state, not later patch versions.

No code change in this release — only the changelog entry, recording the milestone.

## [v0.1.17] — 2026-04-25

### Removed — README pitch paragraph and outdated local whitepaper copy
- README's second paragraph (the "Frontier-coding-agent ergonomics for 5–25 GB models…" pitch) — redundant with the Substack link in the next paragraph and with the more detailed coverage further down (benchmark table, Roadmap, Architecture).
- `docs/whitepaper.md` — outdated local copy, prior version to the published Substack article. The Substack post (linked from the README and from `docs/architecture.md`) is the canonical version.
- Corresponding `whitepaper.md` entry in the README's Architecture file-tree.

No code change. Tests unchanged.

## [v0.1.16] — 2026-04-24

### Added — `browser-extract-retention` extension
New extension at `.pi/extensions/browser-extract-retention/` prunes raw `BrowserExtract` tool-results from conversation history on every turn. Keeps the **2 most-recent** extractions raw (the model may still be deciding what to `EvidenceAdd`), replaces older ones with a compact placeholder:

```
[BrowserExtract tool-result pruned — N chars originally extracted]
URL: https://…
Evidence saved from this extraction: e1 (note1); e2 (note2). Use EvidenceGet <id> to recall any snippet.
```

The placeholder walks message history backward to find the originating `BrowserNavigate` call (so the URL is cited accurately) and cross-references the session's Evidence store to list any saved snippets from that URL. Hooks the `context` event — non-destructive, fires before each LLM call.

**Why this matters.** On a GAIA trial reading several pages, the agent accumulates 20–40 KB of raw chunk text in context while separately distilling the relevant bits via `EvidenceAdd`. The raw text is redundant post-distillation and contaminates reasoning. The extension lets `BrowserExtract` behave like a working buffer that drains as evidence crystallizes — without dropping anything the model can still retrieve via `EvidenceGet`.

Measured on real Wikipedia content (`en.wikipedia.org/wiki/GAIA`, 3 extracts): **28.4 % context reduction (2253 chars saved)** from pruning 1 of 3 extracts at retention = 2. Savings compound linearly with extract count.

### Fixed — latent `page.evaluate` bug in `browser` extension
`.pi/extensions/browser/index.ts` was passing the Readability extraction script to Playwright as a *string* containing `() => { ... }`. Playwright evaluates strings as JavaScript expressions; a function literal evaluates to a function *value*, not an invocation, and serializes to `undefined` across the page/Node boundary. Both the primary and fallback paths had this bug, which meant `BrowserExtract` was silently returning empty text against some pages (and partial text on others, depending on Playwright version / page structure).

Replaced both `page.evaluate("() => {...}")` calls with real function references (`page.evaluate(readablePageText)`, `page.evaluate(fallbackPageText)`) so Playwright auto-invokes and the return value serializes correctly. Verified against real Wikipedia pages (Apollo_11, GAIA, Terminal_Bench) — all three now return > 2 KB of readable text.

### Tests
- `retention.test.ts` — 11 unit tests for `pruneMessages` + `buildPlaceholder` (URL walk-back, rank-from-end, already-pruned idempotency, evidence source matching, retain = 0 edge case, only-touches-BrowserExtract invariant).
- `live-integration.test.ts` — 3 tests running Playwright against live Wikipedia: baseline chunking, 3-extract GAIA-style trial with evidence, context-size measurement.
- Suite now **95 / 95 passing** (was 92 / 92); typecheck clean.

### Not touched
The in-flight TB 2.0 `k = 5` run (`tb2-leaderboard-k5-2026-04-24__00-34-46`, ~163 / 445 trials) continues on v0.1.15 — retention + browser fix apply only to future GAIA work, not to TB trials.

## [v0.1.15] — 2026-04-24

### Added — `llamacpp/qwen3.6-27b` registered for experimentation
Alibaba released Qwen3.6-27B (dense, 27 B params, 262 K ctx) on 2026-04-22 with claims of outperforming its own 397 B MoE flagship on agentic coding benchmarks. Added the model to the provider extension and settings.json so it's a one-flag switch for future experiments:

- `.pi/extensions/llama-cpp-provider/index.ts` — registers `llamacpp/qwen3.6-27b` alongside the existing A3B and 9B entries.
- `.pi/settings.json` — adds a `llamacpp/qwen3.6-27b` profile with the same `benchmark_overrides.terminal_bench` / `benchmark_overrides.gaia` shape as the A3B profile.

**35 B-A3B remains the benchmarking target.** Empirical sweep on 8 GB VRAM: the 27 B dense topped out at **5 tok/s** (Q3_K_XL, `-ngl 26`) — only ~28 % faster than the 4 tok/s Q4 baseline, and ~7 × slower than the 35 B-A3B's 38 tok/s. The MoE architecture of the A3B (35 B total / 3 B active, experts in RAM via `--n-cpu-moe 999`) is what makes a 35 B model viable on a laptop 8 GB GPU; a dense 27 B can't match it without ≥ 24 GB VRAM. The 27 B entry stays registered for users on larger hardware (or for future quant experiments), but all in-flight and upcoming benchmark runs use `llamacpp/qwen3.6-35b-a3b`.

### Operational note (not in git)
The paused TB 2.0 `k=5` run (`tb2-leaderboard-k5-2026-04-24__00-34-46`) was resumed via `harbor job resume` against the A3B server after the model sweep concluded. 158 / 445 trials were already done; resumption picks up at trial 159. No trial data was discarded.

No code change beyond the two file edits above. Tests unchanged.

## [v0.1.14] — 2026-04-24

### Added — Roadmap section in README
Adds a `## Roadmap` section to the README, positioned right after the benchmark-results table, explaining that the near-term focus is **benchmarking to map the impact radius** of the whitepaper's scaffolding — not new features. Sequenced as:

1. Aider Polyglot — done (45.56 % → 78.67 %)
2. Terminal-Bench-Core v0.1.1 — done (40.0 %)
3. Terminal-Bench 2.0 — in progress
4. GAIA — next (stresses the evidence-before-answer protocol on a non-coding benchmark)
5. SWE-bench Verified — after GAIA (longest-horizon multi-file patch test)

**Improvement experiments come after that baseline is in place**, targeting specific failure patterns the data will expose (thinking-budget behavior on long-horizon tasks, `deliberate.py`-style parallel branches on failure, interactive-process shell recovery).

No code or benchmark-harness changes. `benchmarks/tb_runs/` and `benchmarks/harbor_runs/` remain gitignored — the in-flight TB 2.0 run is unaffected.

## [v0.1.13] — 2026-04-24

### Fixed — system prompt fidelity
- **Restored the full v0.0.5 `SYSTEM_PROMPT_TEMPLATE` into `AGENTS.md`.** The port's original AGENTS.md was a ~12-line summary that omitted three load-bearing sections from the Python version: **Capabilities & Autonomy**, **Approaching complex tasks**, and **Handling ambiguity**. Pi's built-in system prompt covers generic coding-agent framing, but the little-coder-specific behavioral nudges — the ones whose wording was validated by the 78.67 % Polyglot run — were not carrying through.
- Sections not carried forward: the Python prompt's Multi-Agent, Memory, MCP, Skill (tool), Task-Management, and Plugin descriptions (those tools aren't shipped in the pi port). The Environment block (`date`, `cwd`, `platform`, `git_info`, `claude_md`) is also dropped because pi populates those in its own built-in prompt.
- Added v0.1.0-era additions the Python prompt didn't have: the Write-vs-Edit runtime invariant note, the per-turn context-augmentation explainer (so the model knows what the `## Tool Usage Guidance` and `## Algorithm Reference` blocks are), and the thinking-budget commit-to-implementation rule.

### Action: restarting the TB 2.0 leaderboard run
The `tb2-leaderboard-k5-*` run kicked off on 2026-04-23 was using the simplified AGENTS.md. Killing and relaunching so every trial uses the restored full prompt. ~12 h of compute is discarded; the submission requires a consistent prompt across all 5 × 89 = 445 trials, so partial-run-with-old-prompt-plus-new-trials-with-new-prompt wouldn't be submittable.

Same class of miss as v0.1.10's `benchmark-profiles` temperature bug: a whitepaper-era mechanism silently diverging from the published numbers. No code, extension, or benchmark-harness changes in this release — the only file that changes runtime behavior is `AGENTS.md`.

## [v0.1.12] — 2026-04-24

### Changed
- README opening now restores a direct pointer to the Substack whitepaper — *[Honey, I Shrunk the Coding Agent](https://open.substack.com/pub/itayinbarr/p/honey-i-shrunk-the-coding-agent)* — in the first two paragraphs, framed as "start there for the *why*; stay here for the *how*". v0.1.11's rewrite had relegated the paper link to the results table only; restoring it above the fold is more appropriate for a repo whose headline result comes from that paper.

No code or behavior change.

## [v0.1.11] — 2026-04-24

### Changed — README rewritten for the post-pi-migration audience
Community feedback after the pi port: new users weren't sure how to set little-coder up now that it's pi-based. This release rewrites the README around that concern, modeled after [pi.dev](https://pi.dev)'s terse, conversational style.

- **New lead**: one-sentence what-it-is + a "How it relates to pi" section that explains little-coder is `pi + 16 extensions + 30 skill markdown files + a Python benchmark harness` — not a fork, not a wrapper, just extensions on a plain `package.json` dependency.
- **Setup section reorganized** into clear steps: what-you'll-need → clone+install → serve a model (llama.cpp / Ollama / cloud) → run → (optional) benchmark. Each step does one thing.
- **New Troubleshooting section** for the failure modes new users actually hit: `pi: command not found`, `ECONNREFUSED 127.0.0.1:8888`, missing API-key env warning, extension load failures, benchmark harness not finding pi.
- **Results table** instead of loose paragraphs — each published benchmark number with its exact tag, model, dataset, and link to the per-benchmark write-up. Paper result (v0.0.2), Polyglot 78.67 % (v0.0.5), Terminal-Bench 1.0 40 % (v0.1.4), Terminal-Bench 2.0 (in progress).
- **Architecture diagram updated** to show both `tb_adapter/` and `harbor_adapter/` (TB 1.0 + 2.0), both pilot + status scripts, and the extension count bumped to 16 (evidence-compact now included).
- Citation / Attribution / License sections unchanged.

No code or behavior change. `benchmarks/tb_runs/` and `benchmarks/harbor_runs/` remain gitignored; in-flight run artifacts from the current TB 2.0 run are not included in this commit.

## [v0.1.10] — 2026-04-23

### Fixed — critical status-script reward-field bug
- **`benchmarks/harbor_status.sh` added** with the *correct* field path for harbor's reward schema.
- Harbor stores the verifier reward at **`verifier_result.rewards.reward`** in each trial's `result.json`. My initial inline status queries were looking at top-level `reward` and `parser_results[0].reward` — both of which are `None` in every harbor run. The result was **every in-flight status check reported 0 % accuracy**, regardless of actual passes.
- Concrete consequence during the 89-task TB 2.0 run: I reported "0 / 11 = 0.0 %" and later "0 / 19 = 0.0 %" when actual numbers were **7 / 19 = 36.8 %**. Passes including `prove-plus-comm`, `pytorch-model-cli` (which failed on TB 1.0 — an outright port win), `merge-diff-arc-agi-task`, and four others were silently labeled failures.
- The running TB 2.0 run itself is unaffected — only my reading of it was wrong. `reward.txt` in each trial dir has always had the correct 0/1 value.

`benchmarks/tb_status.sh` (TB 1.0) is unchanged — TB 1.0's `is_resolved` field lives at the top level and that schema was being read correctly.

## [v0.1.9] — 2026-04-23

### Fixed — version string drift
- `package.json` has been stuck at `"version": "0.1.0"` since the pi-port cut, despite tags advancing through v0.1.8. Bumped to **0.1.9** and will sync on future tags.
- `benchmarks/harbor_adapter/little_coder_agent.py::LittleCoderAgent.version()` hardcoded `"0.1.6"` — meant run metadata would misreport the agent version for any future TB 2.0 submission. Now reads dynamically from `package.json` at import time, so it auto-tracks the bumped package version. Falls back to `"unknown"` if the file can't be read.

No runtime behavior change; corrects the metadata that ends up in `result.json` / leaderboard submissions.

## [v0.1.8] — 2026-04-23

### Fixed
- **`benchmarks/harbor_runs/` is now gitignored.** v0.1.7's commit accidentally included ~50 KB of fix-git pilot output (configs, verifier outputs, reward files). Removed from tracking, added to `.gitignore` alongside the existing `benchmarks/tb_runs/` entry. No user-visible runtime behavior change.

## [v0.1.7] — 2026-04-23

### Fixed
- **`benchmarks/harbor_pilot.sh` flag name.** Used `--task-ids` (TB 1.0 convention) where harbor expects `--include-task-name` for per-task filtering from a registry dataset. v0.1.6 shipped with the wrong flag; this release fixes it.
- **Reproducibility note: v0.1.4 did not actually commit `.pi/settings.json`.** My v0.1.4 commit message claimed `max_turns` bumped from 25 to 40, but I forgot to stage the settings file — only the test that asserts `max_turns == 40` and the Python default (`LittleCoderAgent(max_turns=40)`) went in. The **TB leaderboard 40 % run did in fact use max_turns=40** (my local working file had the change and the running `pi` subprocess read it on launch), so the published result stands — but anyone cloning v0.1.4 and running `vitest` would have hit a test failure on a vanilla checkout. The settings.json change landed correctly in v0.1.6; from v0.1.6 onward the setting is committed-and-reproducible.

### Added — empirical verification of the TB 2.0 adapter
- Ran `benchmarks/harbor_pilot.sh fix-git` against `terminal-bench@2.0` (difficulty=easy, expert time 5 min): **reward 1.0, 1 m 50 s**. First real-task confirmation that:
  - harbor's agent discovery via `--agent-import-path benchmarks.harbor_adapter.little_coder_agent:LittleCoderAgent` works.
  - The async `environment.exec()` ↔ sync PiRpc reader-thread bridge via `asyncio.run_coroutine_threadsafe()` is functional.
  - Cwd tracking through the sentinel `pwd` append preserves stateful-shell semantics across tool calls.
  - pi extensions load cleanly in harbor's container environment.

## [v0.1.6] — 2026-04-23

### Added — Terminal-Bench 2.0 (harbor) adapter
little-coder can now run on the new **`terminal-bench@2.0`** dataset (89 tasks) via [harbor](https://github.com/laude-institute/harbor), the framework that replaced the `tb` CLI for TB 2.0. The TB 1.0 adapter (under `benchmarks/tb_adapter/`) is unchanged — it continues to target `terminal-bench-core@0.1.1` and remains the canonical path for the current leaderboard submission.

- **`benchmarks/harbor_adapter/little_coder_agent.py`** — subclasses `harbor.agents.base.BaseAgent`. Implements `name()`, `version()`, `setup()`, and async `run(instruction, environment, context)`. Reuses `benchmarks/rpc_client.py::PiRpc` verbatim — the only novelty is the ShellSession proxy:
  - TB 1.0 proxied `ShellSession` calls to `TmuxSession.send_keys(...)` (sync, pane-parsing).
  - TB 2.0 proxies to harbor's `BaseEnvironment.exec(...)` (async, stdout/stderr/return_code).
  - A new `_HarborShellProxy` class bridges PiRpc's sync reader-thread callback to the async `env.exec` via `asyncio.run_coroutine_threadsafe()` against the loop stashed in `run()`.
  - Stateful-cwd semantics matched by appending `pwd` to each invocation and tracking the result for the next call's `cd <cwd>` prefix.
- **`benchmarks/harbor_pilot.sh`** — pilot launcher (one or more task ids). Mirrors the shape of `tb_pilot.sh` but calls `harbor run --dataset terminal-bench@2.0 --agent-import-path ... --model ...`.
- README headline lists the TB 2.0 readiness alongside TB 1.0's 40 % result.

### Dataset & install notes (not committed, local-only)
- Install harbor: `uv tool install harbor` (binary ends up at `~/.local/bin/harbor`; version tested: 0.4.0).
- Download TB 2.0 tasks locally for inspection: `harbor dataset download terminal-bench@2.0` — 89 tasks, different layout from TB 1.0 (`task.toml` + `instruction.md` + `environment/` + `tests/` per task; no `.docs/instructions.md`). The download landed at `/home/itay-inbar/Documents/terminal-bench-2.0-tasks/` in my local setup.
- Task set is substantively different from v0.1.1 — no `hello-world`, new families (DNA assembly, compiler verification, kernel debugging, cobol-modernization, feal-cryptanalysis). Pilot-suitable easy candidates will emerge from the first runs.

### Pending before a submission run
- Empirical pilot on 3–5 TB 2.0 tasks to validate the async-exec proxy + cwd tracking under real tasks.
- Leaderboard submission URL / process for TB 2.0 (harbor docs don't yet specify — may differ from the TB 1.0 email-based path).

## [v0.1.5] — 2026-04-23

### Added — Terminal-Bench-Core v0.1.1 result documentation
- **little-coder on Terminal-Bench scored 32 / 80 = 40.0 %** on the full leaderboard-valid `terminal-bench-core@0.1.1` set. Single attempt per task, 6 h 50 min wall clock on an 8 GB RTX 5070 Laptop GPU.
- Run ID `leaderboard-2026-04-23__00-14-03`, executed with [`v0.1.4`](https://github.com/itayinbarr/little-coder/releases/tag/v0.1.4) commit `f4c1b4e`.
- Full write-up with passed/failed task breakdown, turn-cap analysis, extension-activity telemetry, thinking-budget correlation, and v0.2 levers: [`docs/benchmark-terminal-bench-v0.1.1.md`](docs/benchmark-terminal-bench-v0.1.1.md).
- README headline section now lists the TB result alongside the Polyglot headlines.

### Key empirical findings from the run
- The v0.1.4 `max_turns` bump (25 → 40) was empirically correct: cap-hits dropped from ~20 / 80 (projected at 25) to **8 / 80** at 40, and the 72 non-cap tasks passed at **43 %**.
- `skill-inject` fires on 71 / 80 tasks (first runtime-verified evidence that the error-recovery / recency / intent selection is actively engaging per turn — previously silent pre-v0.1.4).
- `thinking-budget` caps fired on 11 tasks — **all 11 failed**. Either selection bias (hard tasks think more, also fail more) or the 3000-token cap is cutting productive reasoning. The v0.2 experiment is to bump TB `thinking_budget` to 5000 and re-run.
- Quality-monitor corrections fired 57 times across 28 tasks, but none of the top-10-most-corrected tasks passed. On TB's long-horizon container debugging, mid-trajectory recovery is harder than on Polyglot.

### Known diagnostic gaps (for v0.2)
- `AgentResult.total_input_tokens` / `total_output_tokens` come through as `0` — the TB adapter doesn't forward pi-ai's usage reports. Cosmetic for leaderboard display but worth fixing.
- 12 failures were `agent_timeout` (harness wall clock), not `unset` (wrong answer) — these are tasks where turn count is fine but each turn is slow.
- `blind-maze-explorer-algorithm.*` (all three variants) failed despite passing the simpler `blind-maze-explorer-5x5` — candidate for a maze-search knowledge entry.

## [v0.1.4] — 2026-04-23

### Added — extension-activity observability
Extensions that were previously silent now emit `ctx.ui.notify` events per decision. The RPC client captures them, the TB adapter persists them per-task, and `tb_status.sh` aggregates them. This closes the diagnostic gap surfaced while the first leaderboard run was in flight — specifically, there was no way to confirm that `skill-inject`'s error-recovery priority was actually firing on failed tool calls.

- `skill-inject` — emits `skill-inject: +N [tool,tool,…]` whenever it injects; captures error-recovery vs recency vs intent selection for later analysis.
- `knowledge-inject` — emits `knowledge-inject: +N [topic,topic,…]` when a knowledge entry scores ≥ threshold and fits the budget.
- Existing `thinking-budget`, `quality-monitor`, `turn-cap`, `evidence-compact`, `output-parser` notify events were already there, now surfaced in the metrics.
- `benchmarks/rpc_client.py::PiRpc.notifications()` — new public method returning accumulated notify events.
- `benchmarks/tb_adapter/little_coder_agent.py` — writes a `=== pi notifications (N) ===` block to each task's `little_coder.log`.
- `benchmarks/tb_status.sh` — new `── metrics ──` section: tool calls per task (avg/median/min/max), turn-cap hits, tool breakdown, per-extension fire counts. Gracefully prints `N/A` for runs launched against pre-0.1.4 code.

### Changed — Terminal-Bench turn-cap: 25 → 40
`benchmark_overrides.terminal_bench.max_turns` raised from **25 to 40** in `.pi/settings.json`, and the default `LittleCoderAgent(max_turns=)` kwarg bumped to match.

Empirical basis: the first 10 tasks of the v0.1.1 leaderboard-valid run hit 25 calls in **5/10 cases** — all five were on failed tasks, strongly suggesting the cap (not the model) was the binding constraint. The 2 passes used 15 and 23 turns, both under 25 and well under 40. The new headroom costs nothing on passes and gives failing trajectories room to recover.

### Does not change
- `gaia` max_turns remains at 30 (different workload, different budget — revisit if GAIA fails similarly).
- Polyglot has no `max_turns` override (Python runs use pi's default, typically ~50).
- Tool schemas, protocol, environment-variable names, other benchmark_overrides fields.

## [v0.1.3] — 2026-04-22

### Added
- `benchmarks/tb_status.sh` — one-shot status dump for an in-flight Terminal-Bench run. Prints process health, elapsed/ETA, completed/remaining counts, current accuracy, per-task pass/fail list, and the currently in-flight container. Auto-detects the newest `leaderboard-*` or `full-*` run dir; accepts an explicit run-id as an argument or `RUN_ID` env var.

## [v0.1.2] — 2026-04-22

### Changed
- **Whitepaper link consolidated to Substack.** Every pointer that used to reference `docs/whitepaper.md` now points at the canonical published version: *[Honey, I Shrunk the Coding Agent](https://open.substack.com/pub/itayinbarr/p/honey-i-shrunk-the-coding-agent)*. The local `docs/whitepaper.md` stays in the repo as a historical artifact (git-based reproduction still works), but README, CHANGELOG `[v0.0.2]`, `docs/architecture.md`, `docs/benchmark-reproduction.md`, and the BibTeX `howpublished` field all direct readers to Substack.

### Community issues from the v0.0.x era — resolved by v0.1.0
The pi port addressed several open issues from the pre-0.1.0 Python codebase:
- [#2](https://github.com/itayinbarr/little-coder/issues/2) *"Unhandled errors when Ollama is not running + crash on accidental shell commands"* (advaitian). Both failure modes are gone in v0.1.0:
  - Provider connection errors (Ollama / llama.cpp unreachable) surface through pi-ai's typed error path and pi's TUI error rendering — no crash, clear message.
  - Accidental shell-command-as-prompt (`ls -alrt`) is sent to the model as ordinary input; pi treats it as a user message rather than executing. The explicit `!command` editor prefix is the opt-in shell channel.
- [#3](https://github.com/itayinbarr/little-coder/issues/3) *"Context handling with llama-server"* (cmhamiche). v0.0.x hardcoded context limits in `local/config.py`; v0.1.0 reads them from `.pi/settings.json`'s `little_coder.model_profiles.<provider>/<model>.context_limit`, which users can freely override (32 K default, 262 K is one settings edit away). Matches whatever `llama-server -c <N>` is serving.
- [#4](https://github.com/itayinbarr/little-coder/issues/4) *"multiple custom providers?"* (mpetruc). `pi.registerProvider()` composes — see `.pi/extensions/llama-cpp-provider/index.ts` in the repo, which registers both `llamacpp/*` and `ollama/*` in one file. Additional providers are added by extra `pi.registerProvider()` calls (or by dropping a `~/.pi/agent/models.json` entry, per pi's docs).

## [v0.1.1] — 2026-04-22

### Changed
- **Strip leftover `little-coder-pi` references.** The 0.1.0 cut had the working-name `little-coder-pi` leaking into a handful of cosmetic places. Everything now reads `little-coder`:
  - `AGENTS.md` H1.
  - `.pi/extensions/checkpoint/`: snapshot directory is now `~/.little-coder/checkpoints/<session>/` (was `~/.little-coder-pi/...`).
  - `.pi/extensions/extra-tools/`: `webfetch` User-Agent is now `little-coder/0.1`.
  - `.pi/extensions/browser/`: Playwright launcher User-Agent reads `Mozilla/5.0 (little-coder research agent)`.
  - `.pi/extensions/hello/`: startup notify message.
  - `benchmarks/tb_adapter/`: module docstring + per-task log filename (`little_coder.log`).
  - `benchmarks/rpc_client.py`, `benchmarks/aider_polyglot.py`: module docstrings.
  - `package-lock.json`: `name` field (package.json was already `little-coder`).
- **Terminal-Bench adapter display name.** `LittleCoderAgent.name()` already returned `little-coder` in 0.1.0 (the leaderboard (agent × model) pair is unaffected), but the adapter class docstring and log filename now match.

### Does not change
- Behavior. 81 TypeScript tests + 4 Python tests still pass, `tsc --noEmit` clean.
- Tool schemas, JSON protocol names, environment-variable names (`LITTLE_CODER_*`), or the whitepaper's mechanism contracts.
- Any in-flight long-running job: the leaderboard TB run launched under 0.1.0 loaded its extension code at startup and continues writing to the old checkpoint path for its lifetime — cosmetic only, checkpoints are best-effort and independent of task results.

## [v0.1.0] — 2026-04-22

### Changed — architecture port to pi
v0.1.0 is a ground-up port of the agent from a hand-rolled Python substrate (CheetahClaws/ClawSpring-derived) onto **pi** ([`@mariozechner/pi-coding-agent`](https://github.com/badlogic/pi-mono) v0.68.1). pi provides the agent loop, multi-provider abstraction, TUI, compaction, session tree, and extension model; little-coder rebuilds every small-model mechanism on top of it as first-class pi extensions. The whitepaper's claim about scaffold-model fit is preserved — nothing that the paper or the v0.0.5 78.67 % run depended on is dropped.

**For reproducing the original paper result, check out tag [`v0.0.2`](https://github.com/itayinbarr/little-coder/releases/tag/v0.0.2) (commit `1d62bde`)** — the Python codebase that produced the 45.56 % mean is preserved at that tag. The 78.67 % headline is preserved at [`v0.0.5`](https://github.com/itayinbarr/little-coder/releases/tag/v0.0.5).

### Added — fifteen pi extensions under `.pi/extensions/`
- `llama-cpp-provider` — registers `llamacpp/*` and `ollama/*` as OpenAI-compat providers via `pi.registerProvider()`. `LLAMACPP_BASE_URL` / `OLLAMA_BASE_URL` env overrides.
- `write-guard` — overrides pi's built-in `write` tool with the exact Python `_write` refusal string, directing the model to `edit` on existing files.
- `extra-tools` — registers `glob`, `webfetch`, `websearch` (pi already ships `grep` and `find`).
- `skill-inject` — hooks `before_agent_start`, runs the 3-priority selector (error recovery > recency > intent, `_INTENT_MAP` exact port) and appends a `## Tool Usage Guidance` block within the configured token budget.
- `knowledge-inject` — scores algorithm cheat sheets against the user prompt (word=1.0, bigram=2.0, threshold=2.0); publishes `requires_tools` back onto `systemPromptOptions.littleCoder` so skill-inject can cross-reference.
- `output-parser` — exposes `repairJson` + `parseTextToolCalls` (fenced ``` ```tool ```/`json` ``` blocks, `<tool_call>` tags, bare JSON, trailing-comma/single-quote/missing-brace repair, JSON string newline re-escape). Hooks `turn_end` to detect text-embedded tool calls and nudge the model back onto native calling.
- `quality-monitor` — ports `assess_response` + `build_correction_message`. Detects empty responses, hallucinated tool names, repeated-call loops, and malformed-args sentinels; queues a correction via `pi.sendUserMessage({deliverAs: "followUp"})`, capped at 2 consecutive corrections.
- `thinking-budget` — counts `thinking_delta` chars per turn; at `ceil(chars/3.5) > budget` aborts the turn, flips `thinkingLevel` to `"off"`, and queues a "commit to an implementation" follow-up.
- `permission-gate` — ports `_SAFE_PREFIXES` bash whitelist (ls/cat/git log/status/diff, find, grep, rg, python, etc.). Blocks non-whitelisted bash in `auto`/`manual` mode; `accept-all` passes everything.
- `checkpoint` — first-write-wins file snapshots to `~/.little-coder/checkpoints/<session>/` before Write/Edit.
- `tool-gating` — execution-level enforcement of `LITTLE_CODER_ALLOWED_TOOLS` + publishes the list on `systemPromptOptions.littleCoder.allowedTools` so skill-inject filters its budget to the allowed subset.
- `turn-cap` — hard `max_turns` early-break via `turn_start` counter + `ctx.abort()`.
- `benchmark-profiles` — reads `.pi/settings.json`'s `little_coder.model_profiles` + `benchmark_overrides.{terminal_bench,gaia}` and publishes resolved values on `systemPromptOptions.littleCoder`; also sets `temperature` on the outgoing provider payload via `before_provider_request` (pi-ai defaults otherwise).
- `shell-session` — `ShellSession`/`ShellSessionCwd`/`ShellSessionReset` with two backends: **tmux-proxy** via `extension_ui_request` (the TB adapter routes commands back to the TB `TmuxSession`) and **subprocess** (`child_process.execSync`). Preserves ANSI-strip, 200-line head/tail truncation + duplicate-line collapse, `[exit=N cwd=… timed_out=…]` footer, pager neutralization.
- `browser` — Playwright-powered `BrowserNavigate`/`Click`/`Type`/`Scroll`/`Extract`/`Back`/`History` with per-session lazy `Page`, inlined Readability JS, 2 KB chunked extract with `{cursor, next, has_more}` footer, graceful degradation when Playwright isn't installed.
- `evidence` — `EvidenceAdd`/`Get`/`List` with per-session in-memory store, 1 KB snippet cap, UUID entry IDs.
- `evidence-compact` — on `session_compact` emits the `[Preserved evidence from earlier in the conversation follows.]` bridge follow-up with entry count. The Python version's `_PRESERVE_TOOL_NAMES` set is architecturally unnecessary in the TS port (evidence lives in extension state, not message history).

### Added — Python RPC harnesses (`benchmarks/`)
- `rpc_client.py::PiRpc` — spawns `pi --mode rpc --no-session` with explicit `-e <abs_path>` for every extension (pi's auto-discovery scans only `cwd/.pi/extensions/`, which fails when pi's cwd is an exercise directory). Demuxes events vs responses vs `extension_ui_request` on a reader thread; handles the TB shell-proxy sidecar. Passes pi's `--tools` flag when `allowed_tools` is set so tool *schemas* (not just execution) match the Python `_filtered_schemas()` behavior.
- `aider_polyglot.py` — Polyglot driver with per-language descriptors (Python wired, others copy verbatim from the v0.0.5 tag). Retry enabled by default. Results flushed atomically.
- `tb_adapter/little_coder_agent.py` — Terminal-Bench `BaseAgent` subclass, still Python, spawns `PiRpc(tb_mode=True, tb_shell_handler=...)` and proxies `__LC_TB_SHELL__` requests through a `_TmuxShellProxy` that ports the Python `_exec_tmux` staged-script sentinel-wrapper strategy verbatim.
- `gaia_scorer.py` — unchanged Python scorer.
- `smoke.py` + `test_rpc_client.py` — end-to-end smoke tester and pytest suite for the RPC client.

### Added — documentation
- `AGENTS.md` — pi's project system prompt (replaces Python `context.py`'s SYSTEM_PROMPT_TEMPLATE).
- `models.json` — reference/documentation copy of the provider registration; `.pi/extensions/llama-cpp-provider/` is the canonical source.
- `.pi/settings.json` — per-model profiles including `benchmark_overrides.terminal_bench` (`thinking_budget: 3000, max_turns: 25, temperature: 0.2`) and `benchmark_overrides.gaia` (`thinking_budget: 2000, max_turns: 30, temperature: 0.4, context_limit: 65536`).

### Removed
- The entire Python implementation: top-level `agent.py`, `tools.py`, `context.py`, `compaction.py`, `config.py`, `providers.py`, `theme.py`, `workspace.py`, `cloudsave.py`, `little_coder.py`, `demo.py`, `memory.py`, `skills.py`, `status_line.py`, `subagent.py`, `tool_registry.py`.
- Python subsystems: `local/`, `memory/`, `multi_agent/`, `skill/` (replaced by `skills/`), `mcp/`, `plugin/`, `modular/`, `task/`, `checkpoint/`, `voice/`, `video/`, `demos/`.
- Python tests under `tests/`, build files `pyproject.toml`, `requirements.txt`.
- Deliberately not ported (out of scope for 0.1.0): sub-agent spawn/manage (`multi_agent/`), MCP client (`mcp/`), persistent memory (`memory/`), task tracker (`task/`), plugin system (`plugin/`), voice input, cloud session sync. These were already peripheral to the whitepaper's result path; users who need them can check out `v0.0.5`.
- Deferred (not strictly a removal — a scope-cut for 0.1.0): `deliberate.py`-style parallel reasoning branches on failure. The pi port relies on `quality-monitor`'s correction follow-up path for between-turn recovery.

### Validation
- **TypeScript:** 81 unit tests across 11 files, `tsc --noEmit` clean.
- **Python:** 4 pytest tests covering PiRpc startup, extension enumeration, env propagation.
- **End-to-end on `llamacpp/qwen3.6-35b-a3b`** (same config as v0.0.5):

| Exercise | Difficulty | Port result | Python run1 baseline |
|---|---|---|---|
| affine-cipher | easy | pass_1 / 42.5 s | pass_1 / 120.6 s (−65 %) |
| bottle-song | moderate | pass_1 / 79.6 s | pass_1 / 127.2 s (−37 %) |
| book-store | hard-but-35B-passed | pass_1 / 73.9 s | fail / 734 s |
| pov | hard | fail / 131 s | pass_1 / 401 s |
| variable-length-quantity | hard | pass_1 / 109 s | pass_2 / 432 s (−4× attempt) |
| connect | hard | fail / 326 s | fail / 739 s |
| zipper | hard | **pass_1 / 130 s** | fail / 670 s |
| wordy | hard | pass_1 / 113 s | fail / 370 s |

Net **6 / 8 = 75 %** on a deliberately-hard subset vs Python run1's 4 / 8 = 50 %. Two exercises Python run1 failed (`zipper`, `wordy`) now pass; one (`pov`) remains a regression within stochastic-variance territory on a tree-rerooting edge case.

### Fixed — two regressions caught during validation
- **Temperature was not reaching the model.** `benchmark-profiles` resolved `profile.temperature = 0.3` but nothing set it on the pi-ai payload. Fixed by having `before_provider_request` **return** a new payload with temperature injected (mutating in place is discarded — pi only adopts returned values). The fix turned `zipper` from fail to pass_1.
- **Tool schemas weren't filtered by `_allowed_tools`.** `tool-gating` blocked execution but pi still presented all registered schemas to the model. Fixed by having `PiRpc` pass pi's `--tools` CLI flag when `allowed_tools` is set; execution-level blocking in the extension stays for defense in depth.

## [v0.0.5] — 2026-04-22

### Added
- **Full Aider Polyglot benchmark run on Qwen3.6-35B-A3B.** 225-exercise end-to-end run scoring **177 / 225 = 78.67 %** with `llamacpp/qwen3.6-35b-a3b` (Qwen3.6-35B-A3B UD-Q4_K_M, 22 GB) via llama.cpp on an 8 GB laptop GPU, no network calls. That's **+33.1 pp over the Qwen3.5 9B two-run mean** (45.56 %) and places little-coder well inside the public leaderboard's top-10 band.
- Per-language results: JavaScript 89.8 %, Python 88.2 %, C++ 84.6 %, Java 76.6 %, Go 74.4 %, Rust 53.3 %. Every language improved by at least +23 pp vs the Qwen3.5 9B baseline.
- 63 exercises flipped `fail → pass` vs both historical Qwen3.5 9B runs; only 4 regressed in the same sense (16 : 1 progression-to-regression ratio) — the improvement is systematic, not stochastic.
- Full write-up with per-language tables, retry-recovery analysis, exercise-level stability, persistent cross-language failures, tool-use metrics, and reproduction instructions: [`docs/benchmark-qwen3.6-35b-a3b.md`](docs/benchmark-qwen3.6-35b-a3b.md).
- Raw per-exercise results: [`benchmarks/results_full_polyglot_run3.json`](benchmarks/results_full_polyglot_run3.json).

### Setup notes for reproducing
- Model: `unsloth/Qwen3.6-35B-A3B-GGUF` `UD-Q4_K_M`
- Serving: llama.cpp built from source, CUDA 13.1, `-DCMAKE_CUDA_ARCHITECTURES=120` (Blackwell)
- Launch: `-ngl 99 --n-cpu-moe 999 --flash-attn on --jinja -c 32768 -t 16` — the `--n-cpu-moe 999` flag is the key VRAM trick (keeps expert weights in RAM; only attention + shared-expert occupy VRAM → fits the whole 35B in 8 GB GPU headroom).
- Agent config: default v0.0.4 little-coder profile for `qwen3.6-35b-a3b` in `local/config.py`, small-model optimizations ON, 32 K context, thinking budget 2048 tokens.
- Runtime: ~27 h cumulative wall-clock across the 225 exercises; sustained ~38 tokens/s during generation.

## [v0.0.4] — 2026-04-21

### Fixed
- `/config` REPL command crashed with `TypeError: Object of type function is not JSON serializable` when the in-memory config held any callable value. The display dict now skips callables and keys that start with `_` alongside the existing `api_key` filter. Reported and authored by [@advaitian](https://github.com/advaitian) in [#1](https://github.com/itayinbarr/little-coder/issues/1); applied in [e9d0bf8](https://github.com/itayinbarr/little-coder/commit/e9d0bf8).

## [v0.0.3] — 2026-04-20

### Added
- **llama.cpp provider** (`llamacpp/...`). `llama-server`'s `/v1/chat/completions` endpoint is a drop-in backend alongside Ollama — no new streaming code, it reuses the OpenAI-compatible path. Point at any loaded GGUF via the `llamacpp/<name>` model prefix. Default endpoint `http://localhost:8888/v1`, overridable with `LLAMACPP_BASE_URL` or `config["llamacpp_base_url"]`.
- **Qwen3.6-35B-A3B model profile** in `local/config.py`. The April 2026 Qwen sparse-MoE (35B total / 3B active, 256 experts, native 262K context) is now a first-class supported model.

### Benchmark result for v0.0.3
- On a consumer laptop (RTX 5070 Laptop 8 GB VRAM Blackwell, i9-14900HX, 32 GB RAM) with llama.cpp + `--n-cpu-moe 999`, `Qwen3.6-35B-A3B UD-Q4_K_M` runs at **38.55 tok/s** generation, **77.94 tok/s** prompt processing. This is comparable to dense-9B speeds despite 4× the parameter count, because MoE keeps compute proportional to the 3B active params while experts stream from RAM.
- The `python/book-store` exercise — which failed Qwen3.5 9B in both full polyglot runs reported in v0.0.2 — **passes on the first attempt** in 86.1 s with `llamacpp/qwen3.6-35b-a3b`. The model correctly identifies the non-obvious `(5, 3) → (4, 4)` grouping optimization (two groups of 4 at 20% off beat a group of 5 at 25% off plus a group of 3 at 10% off) that the greedy solution gets wrong.

### Changed
- `providers.py` header comment and provider list updated to include `llamacpp`.
- Built-in prefix auto-detection still recognises `qwen...` as the Alibaba DashScope cloud provider; use the explicit `llamacpp/` prefix to route a local Qwen GGUF to llama.cpp.

### Preserved
- **Ollama remains the default local backend**. No changes to `stream_ollama()`, its thinking-budget-cap mechanism, the Ollama provider entry, the auto-detect prefixes for `llama/mistral/phi/gemma`, the `/api/chat` streaming path, or `OLLAMA_BASE_URL` env handling. Existing `ollama/...` model IDs continue to work unchanged.
- All tool contracts (Read / Write / Edit / Bash / Glob / Grep / Skill / SubAgent) and the Write-vs-Edit invariant are unchanged.

### Setup pointers
- Build llama.cpp from source with CUDA support (on Blackwell set `-DCMAKE_CUDA_ARCHITECTURES=120`). Prebuilt releases may not yet include the Gated DeltaNet operators required by Qwen3.6.
- Launch `llama-server` with `-ngl 99 --n-cpu-moe 999 --flash-attn on --jinja` for the A3B model. The `--n-cpu-moe` flag keeps expert weights in RAM and puts only attention + shared expert on GPU — the trick that lets 35B total params run on 8 GB VRAM.
- See the provider docstring at the top of [`providers.py`](providers.py) for the full model-string grammar.

## [v0.0.2] — 2026-04-19

### Headline result
- `ollama/qwen3.5` (9.7B, 6.6 GB) + little-coder scored **45.56% mean (±0.94pp)** across two complete 225-exercise Aider Polyglot runs on a consumer laptop with no network calls. On the public leaderboard this sits above `gpt-4.5-preview` (44.9%) and `gpt-oss-120b high` (41.8%). A matched-model vanilla Aider baseline reached 19.11%.

### Initial public release
- Skill-augmented agent loop for small local models (gemma3, gemma4, qwen3, qwen3.5, qwen2.5, llama3.2, phi4-mini).
- Ollama provider with thinking-budget cap (stream-level token counting → abort at budget → retry with `think:false`) to prevent reasoning models from hanging on hard problems while preserving their partial reasoning.
- Multi-provider support (anthropic / openai / gemini / kimi / qwen / zhipu / deepseek / minimax / ollama / lmstudio / custom).
- 8 core tools + Write-vs-Edit tool invariant.
- Aider Polyglot benchmark harness (`benchmarks/aider_polyglot.py`) with per-language transforms, atomic resumable results, and per-run status dashboard.
- Full paper: [*Honey, I Shrunk the Coding Agent* on Substack](https://open.substack.com/pub/itayinbarr/p/honey-i-shrunk-the-coding-agent); two-run reproduction report at [`docs/benchmark-reproduction.md`](docs/benchmark-reproduction.md).
