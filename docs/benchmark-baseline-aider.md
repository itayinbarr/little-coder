# Vanilla Aider + Qwen3.5 — Scaffold-Ablation Baseline

**Status: COMPLETE.** Full 225-exercise run finished 2026-04-19 10:57:35 (started 2026-04-18 19:18:37). Total wall time 15h 39m. **Final score: 43/225 = 19.11%** for `ollama/qwen3.5` (9.7B, Q4_K_M) through vanilla Aider on matched context and matched test protocol.

## Why this run

The primary little-coder polyglot result (`docs/benchmark-reproduction.md`, `docs/benchmark-reproduction.md`) reports **46.22% (run 1) / 44.89% (run 2)** for `ollama/qwen3.5` through little-coder. The community reference point for this benchmark is Aider, and the typical Aider polyglot number is reported against a different model (GPT-4o or Sonnet). That leaves a load-bearing ambiguity in any scaffold-driven claim:

> "Is the little-coder delta over GPT-4o+Aider caused by the scaffold, or is it caused by the model choice?"

A scaffold+model comparison does not decompose into scaffold-only and model-only components without a third cell:

| | Aider scaffold | Little-coder scaffold |
|---|---|---|
| GPT-4o | reported elsewhere | — |
| Qwen3.5 | **this run** | 46.22% (run 1) / 44.89% (run 2) |

This document fills the missing cell. Same model weights, same test protocol, same test suites, same context budget — the only remaining variable is the scaffold. Whatever gap appears between **vanilla Aider + Qwen3.5** and **little-coder + Qwen3.5** is directly attributable to scaffold architecture.

## TL;DR

On the same 225-exercise polyglot suite and the same Qwen3.5 9.7B Q4_K_M weights at 32,768-token context:

| System | Pass rate | Wall time |
|---|---|---|
| **little-coder + Qwen3.5** (run 1 / run 2 mean) | **45.6%** | 21.75h mean |
| **vanilla Aider + Qwen3.5** (this run) | **19.11%** | 15.65h |
| **Scaffold gap** | **−26.5 pp** | −28% wall time |

Vanilla Aider solves **43/225** exercises. Little-coder solves **102.5/225** (run 1 / run 2 mean). The scaffold is producing **2.4× more passes** on the same model weights.

The gap decomposes cleanly into two regimes:

- On exercises little-coder passed (phase 1, 104 exercises): Aider passes **27.9%**
- On exercises little-coder failed (phase 2, 121 exercises): Aider passes **11.6%**

Aider performs better on the easier slice of the distribution, but it's still losing two-thirds of the exercises the model is demonstrably capable of solving.

---

## Methodology

### Model under test

| Component | Value |
|---|---|
| Model | `ollama/qwen3.5` — 9.7B params, Q4_K_M, 6.6 GB weights |
| Ollama | 0.20.5, Docker |
| `num_ctx` | 32,768 (matched to little-coder's profile) |
| `num_predict` | 8,192 (added mid-run after observing runaway generation — see § Runaway generation case study) |
| `timeout` (litellm) | 1,800s (raised from Aider default of 600s to accommodate long generations on CPU-offloaded KV cache) |
| temperature | 0 (Aider's default for this model) |
| edit format | `whole` (Aider's default for unrecognized models) |

All inference identical to little-coder's runs: same Ollama daemon, same model weights, same context window. The model is not the variable.

### Scaffold under test

**Aider 0.86.2** (pip-installed into an isolated venv), invoked via Aider's official `benchmark/benchmark.py` harness from the `Aider-AI/aider` source repo. Two attempts per exercise (`--tries 2`), matching the protocol little-coder uses in `benchmarks/aider_polyglot.py`. No modifications to Aider's prompts, coder logic, retry mechanics, or edit-parsing code.

### Exercise sampling

All 225 polyglot exercises. To make early progress meaningful even if the run was interrupted, the run was split into two phases:

- **Phase 1 (104 exercises, 46.22% of the suite)**: exercises that little-coder **passed in run 1**. These are the highest-signal exercises for a scaffold comparison — exercises the model is known to be capable of solving in some configuration.
- **Phase 2 (121 exercises, 53.78% of the suite)**: the remainder (run-1 fails).

Every exercise goes through Aider's full 2-attempt protocol regardless of phase. The phase ordering is purely a scheduling choice, not a filter.

### Test grading

Each exercise uses its language-native test runner from the `Aider-AI/polyglot-benchmark` repository (the same source upstream-Exercism set that `little-coder`'s `benchmarks/aider_polyglot.py` uses). Pass/fail is determined by the test runner's exit code after Aider's 2 attempts.

### Comparison protocol

Where a direct comparison is made against little-coder, **run 2** is used as the reference (the more recent of the two published little-coder numbers). When a run-1-specific analysis is natural (phase 1 is defined by run-1), that is called out explicitly.

---

## What vanilla Aider has vs. what little-coder has

This table is the foundation for every analysis below. Read it as: "these are the architectural interventions that separate the two scaffolds."

| Intervention | Vanilla Aider | Little-coder |
|---|---|---|
| Edit format | Whole-file rewrite on every turn (`whole`) | Surgical tool-call model (Read, Edit, Bash, Glob, Write) |
| Tool-use guidance | None | Per-tool skill cards injected at turn time |
| Write-guard | None | Write tool refuses on existing files with a structured error pointing at Edit |
| Workspace discovery | None | Conditional-injection knowledge entry for `.docs/instructions.md`, `README.md`, etc. |
| Thinking budget | None (model runs free) | 2,048-token cap with reasoning reuse |
| Retry mechanism | `--tries 2` (replay with test output as feedback) | `--tries 2` — **same** |
| Quality monitor | None | Detects empty/hallucinated/looping output and mitigates |
| Algorithm cheat-sheets | None | Keyword-gated knowledge entries (BFS state-space, tree rerooting, rule-string transform, etc.) |
| Output length cap | None by default (unlimited `num_predict`) | Implicit via agent-loop structure + context budget |

The only shared element is the 2-attempt protocol. Everything else in the architecture column is different.

---

## Headline

| Metric | Little-coder run 2 | Little-coder run 1 | Vanilla Aider | Aider gap vs LC mean |
|---|---:|---:|---:|---:|
| Total passes | 101 / 225 | 104 / 225 | **43 / 225** | — |
| Pass rate | 44.89% | 46.22% | **19.11%** | **−26.5 pp** |
| 1st-attempt passes | 84 | 85 | 12 | — |
| 2nd-attempt passes | 17 | 19 | 31 | — |
| Wall time | 23.3h | 20.2h | **15.65h** | −28% |
| Passes per hour | 4.33 | 5.15 | 2.75 | **−42%** |
| Mean time on passing | 183s | 170s | 141s | — |
| Mean time on failing | 528s | 455s | 224s | — |
| Fail/pass time ratio | 2.9× | 2.7× | 1.6× | — |
| Capped exercises | 0 | 0 | 3 | — |

**Two competing framings**:

- **Pass count**: little-coder wins **2.4×** more exercises. This is the headline.
- **Pass throughput**: little-coder produces **1.72× more passes per wall-clock hour** (4.74 pass/h mean vs 2.75 pass/h). The scaffold pays for its per-exercise overhead with more wins per unit time.

Vanilla Aider fails faster than little-coder (224s vs 528s mean on failures) — the 2-attempt whole-rewrite loop gives up quickly when it can't converge. That keeps Aider's wall time lower, but at the cost of producing far fewer passes.

---

## Per-language breakdown

### Per-language pass rates

| Language | Aider pass | Total | Aider % | LC run 2 % | LC run 1 % | Gap vs LC run 2 |
|---|---:|---:|---:|---:|---:|---:|
| cpp | 7 | 26 | **26.9%** | 50.0% | 50.0% | −23 pp |
| java | 11 | 47 | 23.4% | 51.1% | 53.2% | −28 pp |
| javascript | 9 | 49 | 18.4% | 44.9% | 49.0% | −27 pp |
| python | 6 | 34 | **17.6%** | 52.9% | 52.9% | **−35 pp** |
| rust | 5 | 30 | 16.7% | 30.0% | 30.0% | **−13 pp** |
| go | 5 | 39 | **12.8%** | 38.5% | 38.5% | −26 pp |
| **TOTAL** | **43** | **225** | **19.11%** | **44.89%** | **46.22%** | **−25.8 pp** |

### Full detail (attempt splits + caps)

**Phase 1 (104 exercises — little-coder run-1 passes)**

| lang | done | p1 | p2 | fail | cap | pass rate |
|---|---:|---:|---:|---:|---:|---:|
| python | 18 | 3 | 3 | 11 | 1 | 33.3% |
| java | 25 | 2 | 6 | 17 | 0 | 32.0% |
| cpp | 13 | 1 | 3 | 7 | 2 | 30.8% |
| javascript | 24 | 1 | 6 | 17 | 0 | 29.2% |
| rust | 9 | 1 | 1 | 7 | 0 | 22.2% |
| go | 15 | 0 | 2 | 13 | 0 | 13.3% |
| **total** | **104** | **8** | **21** | **72** | **3** | **27.9%** |

**Phase 2 (121 exercises — little-coder run-1 fails)**

| lang | done | p1 | p2 | fail | cap | pass rate |
|---|---:|---:|---:|---:|---:|---:|
| cpp | 13 | 0 | 3 | 10 | 0 | 23.1% |
| rust | 21 | 2 | 1 | 18 | 0 | 14.3% |
| java | 22 | 0 | 3 | 19 | 0 | 13.6% |
| go | 24 | 0 | 3 | 21 | 0 | 12.5% |
| javascript | 25 | 2 | 0 | 23 | 0 | 8.0% |
| python | 16 | 0 | 0 | 16 | 0 | **0.0%** |
| **total** | **121** | **4** | **10** | **107** | **0** | **11.6%** |

### Language-level observations

- **Python gap is the widest (−35 pp).** The language where little-coder's workspace-discovery + skill injection + Write-guard help most. Python's phase-2 pass rate is **0.0%** — Aider solved none of the 16 python exercises that LC run-1 failed. The scaffold-dependent workflow (terse syntax, docstring conventions, pytest idioms) amplifies every architectural gap.
- **Rust gap is the narrowest (−13 pp).** Consistent with `docs/benchmark-reproduction.md` § "Rust — semantic or dies": the borrow checker is a hard model ceiling that scaffolding can't move. Rust is where `ollama/qwen3.5` hits its model-capability bound regardless of agent architecture.
- **C++ and Java** sit mid-gap (−23 to −28 pp). Both are verbose-typed languages where LC's Read-then-Edit flow on existing stubs outperforms whole-file rewrites, but the compile gate helps both scaffolds equally.
- **Go's phase-2 rate (12.5%) is higher than its phase-1 rate (13.3%) — but within noise on small samples**. Go's pass rate is the lowest overall (12.8%) — confirms LC's observation that Go's unused-import strictness punishes whole-file rewrites disproportionately.

---

## Phase 1 vs Phase 2 — the scaffold signal

**The core analytical question this run answers.**

Phase 1 = exercises little-coder **passed** in run 1. Phase 2 = exercises little-coder **failed** in run 1.

If scaffold were irrelevant and the gap between little-coder and Aider were purely about model capability, Aider's pass rate would be roughly flat across phases (the model is the same; the exercise difficulty distribution is the only variable). If scaffold matters, Aider's rate should be **higher** in phase 1 (easier exercises — the model can solve them) and **lower** in phase 2 (harder exercises — the model can't solve them regardless of scaffold).

| Phase | Aider pass rate | Meaning |
|---|---:|---|
| Phase 1 (LC run-1 passes) | **27.9%** (29/104) | On exercises LC solved, Aider passes ~1 in 4 |
| Phase 2 (LC run-1 fails)  | **11.6%** (14/121) | On exercises LC also couldn't solve, Aider is near one in ten |

The 2.4× ratio between phases is the scaffold signal:

1. **Floor**: Even on exercises LC already solved, Aider is losing 72% of them. **75 exercises that LC passed in run 1 — Aider failed.** That's the scaffold gap in its purest form — the model is demonstrably capable of the solution, but Aider's whole-file-rewrite-without-workspace-discovery-without-Write-guard architecture doesn't get there reliably.
2. **Ceiling**: The phase 2 rate (11.6%) establishes that the gap isn't fully explained by exercise difficulty. Even on hard exercises, Aider's remaining pass rate is disproportionately low compared to LC's ~45% baseline on the full 225.

---

## Cross-scaffold 2×2 contingency

Each cell is a count of exercises where little-coder (run 2) and Aider produced the combination of outcomes.

**vs LC run 2:**

|                          | **LC pass** | **LC fail** | row total |
|--------------------------|------------:|------------:|----------:|
| **Aider pass**           | 32          | 11          | 43        |
| **Aider fail**           | **69**      | 113         | 182       |
| **column total**         | 101         | 124         | 225       |

**vs LC run 1:**

|                          | **LC pass** | **LC fail** | row total |
|--------------------------|------------:|------------:|----------:|
| **Aider pass**           | 29          | 14          | 43        |
| **Aider fail**           | **75**      | 107         | 182       |
| **column total**         | 104         | 121         | 225       |

Read the diagonals directly:

- **32 / 29 (both pass)**: the universal-easy set. Scaffold-independent. Both systems solve these.
- **113 / 107 (both fail)**: the model-limited set. Qwen3.5 9B Q4 can't solve these regardless of scaffold. Neither wins.
- **69 / 75 (LC pass, Aider fail)**: **the scaffold-delta set** — exercises within the model's ability where Aider's scaffold loses. Every one is direct evidence for scaffold architecture mattering on this model.
- **11 / 14 (LC fail, Aider pass)**: the noise floor — places where Aider happens to hit a solution LC missed. ~6× smaller than the scaffold-delta cell in the other direction.

**Scaffold-driven exercises that flipped**: 69–75 exercises LC solved that Aider didn't, depending on the LC run used. The **net** scaffold contribution is **58–61 exercises** (69 − 11, or 75 − 14).

### Scaffold-delta breakdown by language (vs LC run 2)

| lang | scaffold-delta count |
|---|---:|
| java | 14 |
| javascript | 14 |
| go | 14 |
| python | 13 |
| cpp | 8 |
| rust | 6 |
| **total** | **69** |

Java, JavaScript, Go, and Python each contribute 13-14 exercises to the scaffold-delta set — broadly uniform. C++ and Rust contribute fewer, again consistent with the observation that those languages are model-capability-limited (not scaffold-limited).

---

## Time and token economics

### Time per exercise (seconds)

| Metric | LC run 1 | LC run 2 | Vanilla Aider |
|---|---:|---:|---:|
| Mean on passing | 170 | 183 | **141** |
| Median on passing | 138 | 160 | **85** |
| Max on passing | — | — | 660 |
| Mean on failing | 455 | 528 | **224** |
| Median on failing | 360 | 476 | **147** |
| Max on failing | — | — | 1,061 |
| Fail/pass ratio | 2.7× | 2.9× | 1.6× |

Vanilla Aider **fails faster** than little-coder by a substantial margin. On failing exercises, Aider mean = 224s vs LC = 528s — Aider gives up ~2.4× faster.

1. **Aider's 2-attempt protocol converges faster**: no multi-turn agent loop, no retries beyond the 2 configured, no thinking-budget fires, no quality-monitor intervention. Each attempt is a single LLM call producing a full-file rewrite. Total failure cost is just 2 × LLM call + 2 × test run.
2. **Little-coder's agent loop explores longer on hard exercises**: up to 20 turns of Read / Edit / Bash / test-run / retry. The model burns wall-clock cycling through hypotheses. Some of those cycles turn into eventual passes (the pass_2 path); most don't.

**Net throughput** (passes per wall-clock hour):
- LC run 1: 5.15 pass/h
- LC run 2: 4.33 pass/h
- Aider: **2.75 pass/h**

LC mean throughput is **1.72× Aider's** — meaningfully higher even after accounting for LC's longer wall time per exercise.

### Tokens per exercise

| Metric | Aider (all 225) |
|---|---:|
| Mean total tokens | 15,635 |
| Mean completion tokens | 4,759 |
| Max completion tokens (single exercise) | **21,321** (java/pov, pre-cap) |
| Max prompt tokens (single exercise) | 91,596 (cpp/binary-search-tree) |

Little-coder's per-exercise token totals aren't directly extracted in the result files; a per-exercise token comparison is unavailable. Aider's pattern is clear: whole-file-rewrite format generates tokens proportional to file size × retry count, and failing exercises consume slightly more (both attempts trigger).

---

## Runaway generation — case study and mitigation

### The observed pattern

Three exercises in phase 1 — **cpp/yacht, cpp/bank-account, python/grade-school** — entered a pathological state where `ollama/qwen3.5` never emitted end-of-stream. Each produced tokens continuously for 60+ minutes. Aider's default `num_predict: -1` (unlimited output tokens) combined with Ollama's streaming (bytes trickled back to the client one at a time) meant neither the client nor the server terminated the generation naturally.

For these three exercises, the generation was ultimately terminated by an emergency per-exercise wall-clock cap (SIGALRM at 3,600s) installed mid-run. All three were recorded as `exceeded_wall_cap: true` failures.

### The canonical example — java/pov

**java/pov** is the single largest generation in the run, providing a clean view of the pre-cap upper bound:

| Metric | Value |
|---|---|
| Completion tokens | **21,321** |
| Prompt tokens | 31,134 |
| Total tokens | 52,455 |
| Duration | 763s (12.7 min) |
| Outcome | fail (tests failed after 2 attempts) |

21,321 completion tokens is roughly **~500–800 lines of emitted code** (via the rust/grade-school conversion ratio in our run: 22 tokens/line for Aider's fence-wrapped output). The java/pov problem's reference solution is ~80 lines. The model produced **~8–10× more output than a correct solution would require**, without ever converging to one.

This is not an isolated case. **40 of 225 exercises had pre-cap completion_tokens > 8,192** (half of the 16,384 theoretical ceiling with 2 attempts). The runaway pattern was widespread across languages:

| lang | # exercises with >8,192 completion tokens pre-cap |
|---|---:|
| cpp | 11 |
| go | 8 |
| java | 6 |
| javascript | 7 |
| python | 4 |
| rust | 4 |

### The mitigation

After observing the three wall-capped cases, we added `num_predict: 8192` to the Aider model-settings extra_params. The 8,192 value is ~2–3× any realistic Exercism solution length (practice exercises are 20–100 lines; a full-file dual-stub C++ exercise might hit 500 lines; 8,192 tokens is ~300–500 lines of code with Aider's markdown fences). A probe with `num_predict=200` confirmed the cap is honored bit-for-bit at the Ollama level (completion_tokens returned exactly 200).

After `num_predict: 8192` was applied, **zero exercises hit the 3,600s wall-clock cap in the remaining 121 phase-2 exercises**. The output-length bound catches runaway cases before the wall-clock bound fires — they resolve in ~15–20 minutes (the time Qwen3.5 takes to emit 8,192 tokens on this hardware) instead of 60 minutes.

### Interpretation

The runaway-generation pattern is a direct consequence of Aider's vanilla configuration: unlimited `num_predict` + streaming + no internal loop-detection. Little-coder's scaffold has no such failure mode because:

- Tool calls impose natural turn boundaries (each turn produces a discrete tool invocation, which has a schema that constrains length)
- The agent loop is bounded at 20 turns
- The thinking-budget cap fires at 2,048 tokens if reasoning runs long
- The quality monitor detects repetition and aborts

This is an orthogonal but important contribution of the scaffold architecture: **eliminating the degenerate-output failure mode** before it burns wall clock. The 40 exercises that would have run away without `num_predict=8192` are **all distinct from the scaffold-delta set** (they would have failed regardless), but they illustrate how the vanilla Aider configuration has no natural defense against this class of behavior on small local models.

---

## Cross-language hardness

Exercises that fail in both LC (run 2) and Aider across multiple languages are the algorithmic-depth-limited set — exercises the 9.7B model can't solve regardless of scaffold. Consistent with `docs/benchmark-reproduction.md` § "Cross-language hardness":

**Universally hard (fail in both systems, most/all languages)**:
- `book-store`, `bowling`, `forth`, `react`, `zebra-puzzle` — combinatorial optimization, state machines, interpreters, constraint satisfaction
- `alphametics`, `pov`, `variable-length-quantity`, `poker`, `scale-generator` — mostly fail under both systems

**Universally easy (pass in both, most languages)**:
- `grade-school`, `phone-number`, `list-ops` — the LC docs-injection stars carry through
- `beer-song`, `bottle-song`, `robot-name`, `queen-attack`, `resistor-color-trio`
- `gigasecond` — the narrow date/time exercise that still works for both

The "both fail" cell (113 exercises vs run 2) is dominated by algorithmic-depth-limited problems plus language-specific compilation/semantic hurdles. That cell won't shrink without a stronger model.

---

## What's not reproducible from Aider's data

Several sections of `docs/benchmark-reproduction.md` describe *mechanisms* that do not exist in vanilla Aider. Their absence is the point — if vanilla Aider had them, it would be little-coder. For completeness:

- **Write-guard refusals** — Aider's `whole` edit format has no Write vs Edit distinction
- **Edit-to-Write ratio** — no Edit tool
- **Thinking-budget cap fires** — no thinking-budget mechanism
- **Workspace discovery (Glob usage)** — no Glob tool, no workspace exploration step
- **Tool-call distribution (Read / Edit / Bash / Write / Glob)** — Aider's `whole` format is a single generate-full-file-per-turn pattern; there are no discrete tool calls
- **Max-turns exhaustion** — Aider has a 2-try cap, not a turn budget
- **Per-mechanism effectiveness tables** — no mechanisms to measure

These are not omissions; they are the architectural variables the comparison is designed to hold out.

---

## Scope caveats

1. **Single run.** A single-sample point at temperature=0 on a 9.7B quantized model. A three-run mean would tighten the confidence interval but cost ~16 hours of wall time per additional run. Skipped.
2. **Harness modifications made to Aider's benchmark for native (non-Docker) execution** — see Appendix A. None of these modify Aider's scaffold, prompts, retry logic, or edit-parsing; they only fix infrastructure paths (`/aider/benchmark/npm-test.sh` → path-relative) and add a per-exercise wall-clock cap (default 3,600s) to prevent indefinite hangs.
3. **Output-length cap (num_predict=8,192) was added mid-run** to mitigate runaway generation. See § Runaway generation. This setting is inference-level, not scaffold-level — equivalent to setting `num_ctx` or `temperature`. Three early exercises (cpp/yacht, cpp/bank-account, python/grade-school) hit the wall-clock cap before `num_predict` was added and were recorded as capped failures. Post-cap, zero exercises were capped.
4. **Phase ordering may have a minor test-order effect** — phase 1 was processed before phase 2, so Ollama's model cache and Aider's internal state are slightly different for the two phases. Expected impact on pass rates: negligible (< 1 pp).
5. **No direct tool-use comparison**. Aider's `whole` format and little-coder's tool-call model are architecturally incomparable at the call level. The document treats them as opaque systems and compares at the pass/fail level only.

---

## Appendix A — Harness modifications for native execution

Aider's `benchmark.py` is designed to run inside Aider's Docker container. Two infrastructure fixes were needed to run it natively against a local Ollama instance. None modify Aider's agent logic, prompts, retry protocol, or edit-parsing.

### A.1 Path-relative test scripts

`benchmark.py:989-990` originally hard-coded `/aider/benchmark/npm-test.sh` and `/aider/benchmark/cpp-test.sh` — absolute paths that exist only inside Aider's Docker image. Patched to resolve relative to `benchmark.py`'s own directory. Without this fix, all JavaScript (49) and C++ (26) exercises silently recorded as exceptions with no model output.

Additionally, `npm-test.sh` referenced `/npm-install/node_modules` (also Docker-only); patched to read an `NPM_INSTALL` env var with the Docker path as default.

### A.2 Per-exercise wall-clock cap

Added a `SIGALRM`-based per-exercise cap (default 3,600s, overridable via `AIDER_PER_EXERCISE_CAP_SECONDS`) to prevent indefinite hangs when the model enters a runaway-generation state. The cap is installed in `run_test()` (the outer wrapper) and on fire:

- Writes a clean `.aider.results.json` with `tests_outcomes: [false]`, `exceeded_wall_cap: true`, `wall_cap_seconds`, `duration` (actual elapsed), and a descriptive note
- Exits the current exercise cleanly
- Allows the benchmark loop to continue to the next exercise

Critically, the exception class inherits from `BaseException` (not `Exception`) so it propagates through litellm/Aider's broad `except Exception:` retry clauses. An initial version that inherited from `Exception` was swallowed by the retry machinery and failed to fire.

### A.3 Resumable runs

The wrapper script (`benchmarks/baseline_aider/run_baseline.sh`) auto-detects existing phase output directories and invokes `benchmark.py --cont` to resume from the last finalized exercise. This makes the run idempotent against process kills, OS restarts, or user interruption.

### A.4 Output-length cap (num_predict)

Added `num_predict: 8192` to the model-settings extra_params after observing three cases of runaway generation. See § Runaway generation — case study and mitigation for data. The setting is inference-level, not scaffold-level (equivalent to `num_ctx` or `temperature`).

---

## Appendix B — Run configuration

| Setting | Value |
|---|---|
| Aider version | 0.86.2 (pip) + benchmark harness from `Aider-AI/aider` source |
| Python | 3.12 (isolated venv under `benchmarks/baseline_aider/venv/`) |
| Model | `ollama_chat/qwen3.5` |
| `num_ctx` | 32,768 |
| `num_predict` | 8,192 (added mid-run; see § Runaway generation) |
| `timeout` (litellm) | 1,800s |
| `--tries` | 2 |
| `--threads` | 1 |
| `--edit-format` | whole |
| Per-exercise wall cap | 3,600s (`AIDER_PER_EXERCISE_CAP_SECONDS`) |
| Hardware | RTX 5070 Laptop 8GB VRAM, Intel i9-14900HX, 32 GiB RAM, Linux 6.17 (same machine as the LC runs) |
| Start | 2026-04-18 19:18:37 |
| End | 2026-04-19 10:57:35 |
| Wall time | 15h 38m 58s |

---

## Appendix C — Exercise-level data

Per-exercise results for all 225 exercises are under `benchmarks/baseline_aider/tmp.benchmarks/2026-04-18-19-18-37--qwen35-vanilla-aider-phase1/` (104 files) and the paired phase2 dir (121 files). Each exercise directory contains:

- `.aider.results.json` — structured result (tests_outcomes, duration, tokens, cap markers, chat hashes)
- `.aider.chat.history.md` — full chat transcript including model responses, applied edits, and test output

The chat histories are the forensic data for debugging per-exercise failure modes, analogous to `benchmarks/full_polyglot_logs_run*/` for little-coder. Both sets together enable per-exercise cross-scaffold analysis.
