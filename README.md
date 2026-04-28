# little-coder

**A coding agent tuned for small local models, built on top of [pi](https://pi.dev).**

The research story behind all this — why scaffold–model fit matters, how a 9.7 B Qwen beat frontier entries on Aider Polyglot, and what the load-bearing mechanisms actually do — is written up on Substack: **[*Honey, I Shrunk the Coding Agent*](https://open.substack.com/pub/itayinbarr/p/honey-i-shrunk-the-coding-agent)**. Start there if you want the "why"; stay here for the "how".

## How it relates to pi

[pi](https://pi.dev) is the minimal substrate — agent loop, multi-provider API, TUI, session tree, compaction, extension model. Four built-in tools (read / write / edit / bash) and a ~1000-token system prompt.

little-coder is **pi + 20 extensions + 30 skill markdown files + a Python benchmark harness**. It doesn't fork pi or shadow its CLI — pi is a plain dependency in `package.json`, and everything little-coder-specific lives under `.pi/extensions/`, `skills/`, and `benchmarks/`. You can mix little-coder with pi packages from anyone else, add your own extensions, or disable ours per-project via `.pi/settings.json`.

If you've never used pi, it's useful to skim [pi.dev](https://pi.dev) first — the rest of this doc assumes pi's model of `--agent-import-path`, `--mode rpc`, and `.pi/extensions/` auto-discovery.

## Paper / benchmark results

| Release | Model | Benchmark | Result |
|---|---|---|---|
| [**v0.0.2**](https://github.com/itayinbarr/little-coder/releases/tag/v0.0.2) (commit `1d62bde`) — the paper | Qwen3.5-9B via Ollama | Aider Polyglot (225 exercises) | **45.56 %** mean of two runs; matched-model vanilla Aider baseline 19.11 %. Paper: [*Honey, I Shrunk the Coding Agent* on Substack](https://open.substack.com/pub/itayinbarr/p/honey-i-shrunk-the-coding-agent). |
| [**v0.0.5**](https://github.com/itayinbarr/little-coder/releases/tag/v0.0.5) — pre-pi Python | Qwen3.6-35B-A3B via llama.cpp | Aider Polyglot | **78.67 %**. [Full narrative](docs/benchmark-qwen3.6-35b-a3b.md). |
| [**v0.1.4**](https://github.com/itayinbarr/little-coder/releases/tag/v0.1.4) — on pi | Qwen3.6-35B-A3B via llama.cpp | Terminal-Bench-Core v0.1.1 (80 tasks) | **40.0 %** in 6 h 50 min. [Write-up](docs/benchmark-terminal-bench-v0.1.1.md). |
| [**v0.1.13**](https://github.com/itayinbarr/little-coder/releases/tag/v0.1.13) — on pi, TB 2.0 leaderboard | Qwen3.6-35B-A3B via llama.cpp | Terminal-Bench 2.0 (89 tasks × 5 trials = 445) | **23.82 %** (106 / 445). [PR #158](https://huggingface.co/datasets/harborframework/terminal-bench-2-leaderboard/discussions/158) — awaiting maintainer merge. |
| [**v0.1.24**](https://github.com/itayinbarr/little-coder/releases/tag/v0.1.24) — on pi, TB 2.0 leaderboard, smaller model | Qwen3.5-9B (Q4_K_M) via llama.cpp (5.3 GB on GPU, 2× faster per-token than the 35B-A3B) | Terminal-Bench 2.0 (89 tasks × 5 trials = 445) | **9.21 %** (41 / 445). [PR #163](https://huggingface.co/datasets/harborframework/terminal-bench-2-leaderboard/discussions/163) — awaiting maintainer merge. |
| [**v0.1.27**](https://github.com/itayinbarr/little-coder/releases/tag/v0.1.27) — on pi, GAIA validation | Qwen3.6-35B-A3B via llama.cpp | GAIA validation set (165 tasks) | **40.00 %** (66 / 165). L1 60.4 % / L2 37.2 % / L3 7.7 %. Test-split run pending. |

All runs used a consumer laptop: i9-14900HX, 32 GB RAM, **8 GB VRAM** on RTX 5070 Laptop (Blackwell). No cloud inference at any point.

---

## Roadmap

The near-term focus is **benchmarking**, not new features. The paper established that scaffold–model fit moves a 9.7 B model from 19 % to 45 % on Aider Polyglot. The open question is: **how wide is the impact radius?** Does the same set of adaptations — Write-vs-Edit invariant, per-turn skill injection, thinking-budget cap, output-repair, quality monitor — help on tasks that *aren't* self-contained coding exercises? What breaks? What compounds?

The plan is to establish a wide baseline before any further scaffolding changes:

1. **Aider Polyglot** — done. 45.56 % (paper, Qwen3.5-9B) and 78.67 % (v0.0.5, Qwen3.6-35B-A3B).
2. **Terminal-Bench-Core v0.1.1** — done. 40.0 % (v0.1.4).
3. **Terminal-Bench 2.0** — done. Qwen3.6-35B-A3B at **23.82 %** ([PR #158](https://huggingface.co/datasets/harborframework/terminal-bench-2-leaderboard/discussions/158)) and Qwen3.5-9B at **9.21 %** ([PR #163](https://huggingface.co/datasets/harborframework/terminal-bench-2-leaderboard/discussions/163)), both awaiting maintainer merge. The v0.1.24 prompt-repetition fix (re-add tool descriptions + concision guideline, validated by a 4 / 4 pilot on the previously-regressing `prove-plus-comm` task) was the prompt for both submissions.
4. **GAIA** — validation set done at v0.1.27: **40.00 %** (66 / 165) on Qwen3.6-35B-A3B. Per-level L1 60.4 % / L2 37.2 % / L3 7.7 %. Test-split run (301 tasks) pending → leaderboard submission to follow.
5. **SWE-bench Verified** — after GAIA. Multi-file real-world patches; the longest-horizon test of whether the scaffolding generalizes past exercise-scale tasks.

**After that baseline is in place**, the next phase starts: improvement experiments targeted at the specific failure patterns we've seen (thinking-budget / quality-monitor behavior on long-horizon tasks, deliberate.py-style parallel branches on failure, better shell-session recovery for interactive-process traps). No scaffold changes until the data says which ones are worth running.

---

## Install

One-line install (Node.js 20.6+ required):

```bash
curl -fsSL https://raw.githubusercontent.com/itayinbarr/little-coder/main/install.sh | bash
```

Or with npm directly:

```bash
npm install -g little-coder
```

That's the whole install. No clone, no `npm install` in a workspace, no PATH fiddling. `little-coder` is now on your PATH and works from any directory.

## Run

```bash
cd ~/your-project
little-coder --model anthropic/claude-haiku-4-5
```

Other models work the same way:

```bash
little-coder --model openai/gpt-4o-mini "What does this codebase do?"
little-coder --model llamacpp/qwen3.6-35b-a3b   # local llama.cpp server
little-coder --model ollama/qwen3.5             # local Ollama
little-coder --list-models                      # see everything pi knows about
```

The agent uses the directory you launched it from as its working directory — `Read` / `Write` / `Edit` / `Bash` operate on your project, not on little-coder's install path.

For local providers (llama.cpp, Ollama) pi expects *some* value in the API-key env even though local servers ignore it:

```bash
export LLAMACPP_API_KEY=noop
export OLLAMA_API_KEY=noop
```

`LLAMACPP_BASE_URL` and `OLLAMA_BASE_URL` override the defaults (`http://127.0.0.1:8888/v1`, `http://127.0.0.1:11434/v1`).

For cloud providers, set the standard env (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.) and pi will discover it.

## Local model setup (optional)

Skip this section if you're using a cloud model.

**Option A — llama.cpp** (fastest for local; supports Qwen3.6-35B-A3B MoE):

```bash
# One-time: build llama.cpp with CUDA (sm_XXX = your GPU arch; Blackwell = 120)
git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp
cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=120 -DLLAMA_CURL=ON
cmake --build build --config Release -j

# Fetch a GGUF
pip install -U "huggingface_hub[cli]"
hf download unsloth/Qwen3.6-35B-A3B-GGUF Qwen3.6-35B-A3B-UD-Q4_K_M.gguf --local-dir ~/models

# Serve it (MoE trick: experts in RAM, attention on GPU → 22 GB model on 8 GB VRAM)
build/bin/llama-server -m ~/models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf \
   --host 127.0.0.1 --port 8888 --jinja \
   -c 16384 -ngl 99 --n-cpu-moe 999 --flash-attn on
```

**Option B — Ollama** (simpler, but slower on MoE):

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3.5        # 9.7B — the paper's model
# or: ollama pull qwen3.6-35b-a3b
```

All small-model-specific extensions auto-disable for large/cloud models so they don't interfere.

---

## Troubleshooting

**`little-coder: command not found`** — npm's global bin directory isn't on your PATH. Run `npm config get prefix` to see where it installed; add `<prefix>/bin` to your PATH. Or reinstall with `sudo` if your prefix needs root.

**`ECONNREFUSED 127.0.0.1:8888`** — llama.cpp isn't running. Start `llama-server` first, or switch `--model` to an Ollama/cloud ID.

**No API key env var warning** — pi expects *some* key even for local providers. Export `LLAMACPP_API_KEY=noop` (or `OLLAMA_API_KEY=noop`) before launching.

**Extension load failures on startup** — run `little-coder --list-models --verbose`; extension errors surface there. If the install looks corrupt: `npm uninstall -g little-coder && npm install -g little-coder`.

**Node version too old** — little-coder needs Node ≥ 20.6.0. Check with `node --version`. Easiest fix: `nvm install 20 && nvm use 20`.

---

## Developing little-coder locally

If you want to hack on the extensions or skills:

```bash
git clone https://github.com/itayinbarr/little-coder.git
cd little-coder
npm install
npm link            # makes the local checkout available as `little-coder`
little-coder --model anthropic/claude-haiku-4-5
```

To unlink: `npm unlink -g little-coder`.

The benchmarks harness (`benchmarks/`) is dev-only and not shipped with the npm package. Run it from a clone with `python3 benchmarks/aider_polyglot.py …` etc.

---

## Architecture

```
little-coder/
├── .pi/
│   ├── settings.json               # per-model profiles + benchmark_overrides (terminal_bench, gaia)
│   └── extensions/                 # 20 TypeScript extensions, auto-discovered by pi
│       ├── llama-cpp-provider/     # registers llamacpp/* and ollama/* as OpenAI-compat providers
│       ├── write-guard/            # Write refuses on existing files — the whitepaper invariant
│       ├── extra-tools/            # glob, webfetch, websearch (pi ships grep/find)
│       ├── skill-inject/           # per-turn tool-skill selection (error > recency > intent)
│       ├── knowledge-inject/       # algorithm cheat-sheet scoring (word=1.0, bigram=2.0, threshold=2.0)
│       ├── output-parser/          # repair malformed ```tool, <tool_call>, bare JSON
│       ├── quality-monitor/        # empty / hallucinated / loop detection + correction follow-up
│       ├── thinking-budget/        # cap thinking tokens per turn, retry with thinking off
│       ├── permission-gate/        # bash whitelist (ls, cat, git log/status/diff, etc.)
│       ├── checkpoint/             # snapshot files before Write/Edit
│       ├── tool-gating/            # enforces _allowed_tools at exec + schema levels
│       ├── turn-cap/               # max_turns abort (Polyglot unbounded, TB 40, GAIA 30)
│       ├── benchmark-profiles/     # reads settings.json → systemPromptOptions + sets temperature
│       ├── shell-session/          # ShellSession[Cwd|Reset] — tmux-proxy + subprocess backends
│       ├── browser/                # Playwright BrowserNavigate/Click/Type/Scroll/Extract/Back/History
│       ├── evidence/               # EvidenceAdd/Get/List — per-session store, 1 KB snippet cap
│       └── evidence-compact/       # preserves evidence across pi's auto-compaction
├── skills/                         # 30 markdown files the extensions inject on demand
│   ├── tools/*.md                  #   14 tool-usage cards
│   ├── knowledge/*.md              #   13 algorithm cheat sheets
│   └── protocols/*.md              #    3 research/cite/decomposition workflows
├── benchmarks/
│   ├── rpc_client.py               # PiRpc — spawns `pi --mode rpc`, demuxes events + UI requests
│   ├── aider_polyglot.py           # Polyglot driver with per-language transforms
│   ├── tb_adapter/                 # Terminal-Bench 1.0 BaseAgent (tmux-proxy)
│   ├── harbor_adapter/             # Terminal-Bench 2.0 BaseAgent (async env.exec proxy)
│   ├── tb_pilot.sh / harbor_pilot.sh
│   ├── tb_status.sh / harbor_status.sh
│   └── test_rpc_client.py
├── AGENTS.md                       # project system prompt (pi discovers it automatically)
├── models.json                     # documented provider registration (extension is canonical)
└── docs/
    ├── benchmark-*.md              # per-benchmark narratives
    └── architecture.md             # v0.0.5-era Python architecture (historical)
```

**Key invariant.** pi is a minimal base by design. Every little-coder mechanism ships as a pi extension that hooks pi's lifecycle events (`before_agent_start`, `context`, `before_provider_request`, `tool_call`, `tool_result`, `turn_end`, `session_compact`). Extensions are independent and can be enabled/disabled per deployment via `.pi/settings.json`. If you don't want one, delete its directory or disable it in settings; if you want to add another, drop it next to the existing ones.

---

## Reproducing the paper (v0.0.2)

```bash
git clone https://github.com/itayinbarr/little-coder.git
cd little-coder
git checkout v0.0.2
# Follow that version's README for its Python setup (pip install -e .)
```

The paper ran `ollama/qwen3.5` through the Python little-coder at commit **`1d62bde`** (tag [`v0.0.2`](https://github.com/itayinbarr/little-coder/releases/tag/v0.0.2)). The 45.56 % mean figure is the average of two full 225-exercise runs on that exact codebase. For the 78.67 % headline, check out tag [`v0.0.5`](https://github.com/itayinbarr/little-coder/releases/tag/v0.0.5) — both are pre-pi Python and follow the pre-pi setup.

---

## Citation

```bibtex
@misc{inbar2026littlecoder,
  title        = {little-coder: A Coding Agent Optimized for Small Local Language Models},
  subtitle     = {Architectural Adaptation Lets a 9.7B Model Outperform Frontier Models on Aider Polyglot},
  author       = {Inbar, Itay},
  year         = {2026},
  month        = apr,
  howpublished = {\url{https://open.substack.com/pub/itayinbarr/p/honey-i-shrunk-the-coding-agent}},
  note         = {White paper}
}
```

---

## Attribution

little-coder v0.0.x was a derivative work of [CheetahClaws / ClawSpring](https://github.com/SafeRL-Lab/clawspring) by SafeRL-Lab, Apache 2.0. That upstream provided the Python agent substrate, tool system, multi-provider support, and REPL.

little-coder v0.1.0+ replaces that substrate with **[pi](https://github.com/badlogic/pi-mono)** (`@mariozechner/pi-coding-agent`) by Mario Zechner — Apache 2.0 / MIT. pi provides the agent loop, provider abstraction, TUI, and extension model. little-coder rebuilds its small-model adaptations on top of pi as extensions.

All little-coder-specific mechanisms — Write-vs-Edit invariant, skill / knowledge injection, thinking-budget cap, output-parser, quality-monitor, per-model profiles, per-benchmark overrides, ShellSession / Browser / Evidence tool families, evidence-aware compaction — are preserved across versions.

---

## License

Apache 2.0 — see [LICENSE](LICENSE) for details. NOTICE tracks upstream attribution.
