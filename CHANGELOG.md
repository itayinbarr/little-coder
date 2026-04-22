# Changelog

All notable changes to little-coder are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and little-coder's public interface (CLI, providers, tools, skills) follows semver starting at `v0.0.1` post-rename.

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
- Full paper at [`docs/whitepaper.md`](docs/whitepaper.md); two-run reproduction report at [`docs/benchmark-reproduction.md`](docs/benchmark-reproduction.md).
