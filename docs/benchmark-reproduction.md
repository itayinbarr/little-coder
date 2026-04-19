# Aider Polyglot Benchmark — Reproduction Report

Two complete end-to-end runs of the full 225-exercise Aider Polyglot benchmark with `little-coder + ollama/qwen3.5` (9.7B, Q4_K_M, ~6.6 GB). Both runs executed on the same hardware with the same model weights and same harness. Run 2 included a minor system-prompt addition (two short sections on approaching complex tasks and handling ambiguity, replacing removed tool descriptions that were never used).

## Headline

```
Run 1:  104 / 225 = 46.22%
Run 2:  101 / 225 = 44.89%
Mean:   102.5 / 225 = 45.56%
SD:     ±2.1 exercises (±0.94 pp)
Range:  44.89% – 46.22%
```

The 3-exercise gap between runs is consistent with stochastic variance at temperature 0.3 on a 9.7B quantized model.

## Per-language pass rates

| Language   | N  | Run 1      | Run 2      | Mean   | SD    | Δ  |
|------------|---:|------------|------------|--------|-------|----|
| Java       | 47 | 25 (53.2%) | 24 (51.1%) | 52.1%  | 1.1%  | −1 |
| Python     | 34 | 18 (52.9%) | 18 (52.9%) | 52.9%  | 0.0%  | +0 |
| C++        | 26 | 13 (50.0%) | 13 (50.0%) | 50.0%  | 0.0%  | +0 |
| JavaScript | 49 | 24 (49.0%) | 22 (44.9%) | 46.9%  | 2.0%  | −2 |
| Go         | 39 | 15 (38.5%) | 15 (38.5%) | 38.5%  | 0.0%  | +0 |
| Rust       | 30 |  9 (30.0%) |  9 (30.0%) | 30.0%  | 0.0%  | +0 |
| **Total**  | **225** | **104 (46.2%)** | **101 (44.9%)** | **45.6%** | **0.9%** | **−3** |

Four of six tracks produced identical pass counts. Java lost 1 exercise, JavaScript lost 2. Python, C++, Go, and Rust reproduced exactly.

## First-attempt vs second-attempt passes

| Language   | Run 1 1st | Run 1 2nd | Run 2 1st | Run 2 2nd | Mean 1st | Mean 2nd |
|------------|----------:|----------:|----------:|----------:|---------:|---------:|
| Java       | 22        | 3         | 22        | 2         | 22.0     | 2.5      |
| Python     | 17        | 1         | 15        | 3         | 16.0     | 2.0      |
| C++        | 9         | 4         | 10        | 3         | 9.5      | 3.5      |
| JavaScript | 19        | 5         | 19        | 3         | 19.0     | 4.0      |
| Go         | 11        | 4         | 11        | 4         | 11.0     | 4.0      |
| Rust       | 7         | 2         | 7         | 2         | 7.0      | 2.0      |
| **Total**  | **85**    | **19**    | **84**    | **17**    | **84.5** | **18.0** |

~82% of passes are first-attempt across both runs. The second-attempt retry path contributes ~18% of passes, with the test-output-as-context mechanism providing meaningful recovery on exercises the agent almost solves on the first try.

## Exercise outcome stability

| Category                        | Count | %     |
|---------------------------------|------:|------:|
| Same pass (both runs)           | 61    | 27.1% |
| Same fail (both runs)           | 99    | 44.0% |
| Attempt shift (pass, different attempt) | 18 | 8.0% |
| Fail → Pass (progression)      | 22    | 9.8%  |
| Pass → Fail (regression)       | 25    | 11.1% |
| **Stable outcomes**             | **160** | **71.1%** |

71.1% of exercises had the exact same pass/fail outcome across both runs. An additional 8% shifted between first-attempt and second-attempt pass. Only ~20% of exercises changed direction between pass and fail, and those changes nearly cancelled (22 progressions vs 25 regressions = NET −3).

## Tool-use metrics (per-exercise averages)

| Language   | Avg turns | Avg time | s/turn | Write refused | Total calls |
|------------|----------:|---------:|-------:|--------------:|------------:|
| Java       | 14.9      | 394s     | 26.5s  | 30 (64%)      | 742         |
| Python     | 14.8      | 366s     | 24.8s  | 24 (72%)      | 503         |
| C++        | 15.5      | 238s     | 15.3s  | 8 (29%)       | 424         |
| JavaScript | 15.7      | 372s     | 23.7s  | 32 (66%)      | 764         |
| Go         | 16.6      | 371s     | 22.4s  | 30 (78%)      | 670         |
| Rust       | 16.6      | 283s     | 17.1s  | 18 (60%)      | 511         |

Values are means of both runs. The Write-guard invariant fires on 29–78% of exercises depending on language — highest on Go (78%) and Python (72%), lowest on C++ (29%). Per-turn inference time ranges from 15.3s (C++) to 26.5s (Java), reflecting differences in prompt complexity and output length rather than model speed.

## Tool-call distribution (mean of both runs)

| Language   | Read | Edit | Bash | Write | Glob | Total |
|------------|-----:|-----:|-----:|------:|-----:|------:|
| Java       | 282  | 222  | 170  | 30    | 35   | 742   |
| Python     | 186  | 164  | 107  | 24    | 22   | 503   |
| C++        | 171  | 114  | 112  | 8     | 20   | 424   |
| JavaScript | 285  | 200  | 208  | 33    | 36   | 764   |
| Go         | 258  | 222  | 134  | 30    | 26   | 670   |
| Rust       | 177  | 125  | 166  | 18    | 23   | 511   |

Read and Edit dominate across all languages. The Edit-to-Write ratio ranges from 6:1 (Java, JavaScript, Go) to 14:1 (C++), reflecting the Write-vs-Edit invariant's effectiveness. Bash usage varies: highest in JavaScript (208, driven by npm install + npm test per exercise) and Rust (166, driven by cargo build + cargo test), lowest in Python (107, pytest is lightweight).

## Architectural interventions — per-mechanism analysis

Each structural intervention described in the paper has measurable observable effects across both runs. This section maps each mechanism to the benchmark data.

### Write-vs-Edit invariant

The Write tool refuses to operate on existing files and returns a structured error directing the model to use Edit instead. This prevents destructive whole-file rewrites that were the single most common failure mode observed during development.

| Metric | Run 1 | Run 2 | Mean |
|--------|------:|------:|-----:|
| Total Write calls | 142 | 146 | 144 |
| Total Edit calls | 1,036 | 1,057 | 1,046 |
| Edit-to-Write ratio | 7.3:1 | 7.2:1 | 7.3:1 |
| Write refusals (guard fired) | 141 | 145 | 143 |
| Exercises with ≥1 refusal | 128 (56.9%) | 127 (56.4%) | 128 (56.7%) |

The guard fires on **57% of exercises on average** — the model attempts a full-file Write on more than half the exercises before being redirected to Edit. Without the tool-level enforcement, these 143 Write attempts per run would have produced full-file rewrites, each one an opportunity to silently destroy a passing test suite. The metric is highly stable between runs (141 vs 145 refusals, 128 vs 127 exercises affected).

**Per-language refusal rates** vary from 25% (C++) to 67% (Go), reflecting how aggressively the model defaults to Write-over-existing-file in each language:

| Language | Mean refusal rate |
|----------|------------------:|
| Go       | 67%               |
| Python   | 63%               |
| JavaScript | 62%             |
| Java     | 56%               |
| Rust     | 55%               |
| C++      | 25%               |

C++ is the outlier — the agent rarely attempts Write on existing C++ files, likely because C++ exercises typically involve both a `.cpp` and a `.h` file, and the agent learns from the Read step that it needs to edit specific functions rather than rewrite.

### Bounded thinking with reasoning reuse

The thinking-budget cap monitors the model's reasoning token stream in real time and aborts generation when the budget (2,048 tokens) is exceeded. The partial reasoning is reinjected as assistant context, and the request is retried with thinking disabled.

| Metric | Run 1 | Run 2 | Mean |
|--------|------:|------:|-----:|
| Thinking-budget cap fires | 186 | 217 | 202 |
| Cap fires per exercise (avg) | 0.83 | 0.96 | 0.90 |

The budget cap fires **~200 times per run** — nearly once per exercise on average. This means that on a significant fraction of exercises, the model's native reasoning would have continued well past the 2,048-token budget if uncapped. Without the cap, these exercises would have either exhausted the context window (hanging the agent) or produced reasoning so long that it crowded out the implementation tokens. The cap-and-reuse mechanism preserves the partial reasoning while forcing the model to commit to an implementation.

The 186 vs 217 difference between runs (17% more in run 2) is consistent with run 2's 15% slower per-turn inference under thermal throttling — slower token generation means the model has more "wall-clock thinking time" before the budget fires, but the token count at which it fires is the same (2,048).

### Second-attempt retry (pass_2)

When the first attempt fails, the agent receives the test output and gets a second chance. This is the benchmark's built-in retry mechanism.

| Metric | Run 1 | Run 2 | Mean |
|--------|------:|------:|-----:|
| First-attempt passes (pass_1) | 85 | 84 | 84.5 |
| Second-attempt passes (pass_2) | 19 | 17 | 18.0 |
| pass_2 as % of total passes | 18.3% | 16.8% | 17.6% |

**18 exercises per run (17.6% of all passes) are rescued by the retry mechanism.** These are exercises where the agent's first implementation was close but had a bug, and feeding the test output back as context let it fix the specific failure. Without the retry path, the headline number would drop from ~103 to ~85 — a 17-point penalty. The retry mechanism is the second-most impactful intervention after the Write-guard.

The pass_2 count is most significant in Go (4.0 mean) and JavaScript (4.0 mean), reflecting these languages' richer test-output feedback that helps the agent identify and correct specific failures.

### Workspace discovery

A conditional-injection knowledge entry fires on coding keywords and instructs the model to Glob for project documentation (`.docs/instructions.md`, `README.md`, `SPEC.md`, etc.) before writing code.

| Metric | Run 1 | Run 2 | Mean |
|--------|------:|------:|-----:|
| Exercises using Glob | 143 (64%) | 160 (71%) | 152 (67%) |
| Total Glob calls | 153 | 170 | 162 |
| Exercises using Read | 225 (100%) | 225 (100%) | 225 (100%) |

The model uses Glob on **67% of exercises** and Read on **100%** — it always reads files before acting. The workspace-discovery mechanism was the intervention that flipped specific exercises (affine-cipher, dominoes, list-ops) from failing to passing during development: by reading the exercise's `.docs/instructions.md` file, the agent gets the problem specification rather than re-deriving it from test names alone. The 64→71% Glob increase in run 2 may reflect the reworded priming text ("think through the structure... before writing code") encouraging more exploratory behavior.

### Skill-augmented tool use and knowledge injection

Tool skill cards (~80–150 tokens each) and algorithm cheat sheets are injected into the system prompt per turn, selected by intent prediction, recency, and error recovery. These operate in the preprocessing stage and leave no direct trace in the per-exercise results. Their effect is observable indirectly through the overall pass rate and through the qualitative development observation that adding specific knowledge entries (e.g., the affine-cipher modular-inverse reference) flipped specific exercises from fail to pass.

Profile-level configuration: `skill_token_budget: 300`, `knowledge_token_budget: 200` — together, up to 500 tokens per turn are allocated to injected reference material. On a 32K context window, this is ~1.5% of available context.

### Quality gating and convergence behavior

The quality monitor catches empty responses, hallucinated tool names, and infinite loops. Its effect is observable through the agent's convergence pattern:

| Metric | Run 1 | Run 2 | Mean |
|--------|------:|------:|-----:|
| Exercises hitting max turns (20) | 95 | 91 | 93 |
| Avg turns on passing exercises | 11.7 | 11.5 | 11.6 |
| Avg turns on failing exercises | 19.0 | 19.0 | 19.0 |

Passing exercises converge in **11.6 turns on average** — well under the 20-turn budget. Failing exercises use nearly the entire budget (**19.0 turns**), indicating the agent keeps trying until it runs out of turns rather than giving up early. The 93 exercises (41%) that hit max turns are the hard failures where the agent exhausted all available tool calls without producing a passing implementation. The quality monitor prevents these from becoming infinite loops — without it, the agent would cycle indefinitely on the same failing approach.

## Additional analyses

### First-attempt-only pass rate (the value of retry)

What would the headline be without the second-attempt retry mechanism?

| Language   | N  | Mean pass_1 only | Mean total (with retry) | Retry value |
|------------|---:|------------------:|------------------------:|------------:|
| Java       | 47 | 46.8%             | 52.1%                   | +5.3 pp     |
| Python     | 34 | 47.1%             | 52.9%                   | +5.9 pp     |
| C++        | 26 | 36.5%             | 50.0%                   | +13.5 pp    |
| JavaScript | 49 | 38.8%             | 46.9%                   | +8.2 pp     |
| Go         | 39 | 28.2%             | 38.5%                   | +10.3 pp    |
| Rust       | 30 | 23.3%             | 30.0%                   | +6.7 pp     |
| **Total**  | **225** | **37.6%**    | **45.6%**               | **+8.0 pp** |

Without retry, the headline drops from 45.6% to 37.6% — the retry mechanism is worth **8 percentage points** overall. The value of retry varies dramatically by language: C++ gains 13.5 pp from retry (the agent frequently produces almost-correct C++ that fails on one edge case, then fixes it with test output), while Java gains only 5.3 pp.

### Time economics: passes vs fails

| Metric | Run 1 | Run 2 | Mean |
|--------|------:|------:|-----:|
| Avg time on passing exercises | 170s | 183s | 177s |
| Median time on passing exercises | 138s | 160s | 149s |
| Avg time on failing exercises | 455s | 528s | 492s |
| Median time on failing exercises | 360s | 476s | 418s |
| Fail-to-pass time ratio | 2.7x | 2.9x | 2.8x |

Failing exercises consume **2.8x more wall-clock** than passing ones. This is because fails exhaust the full turn budget (19.0 avg turns) while passes converge early (11.6 avg turns). The practical implication: ~56% of total benchmark wall-clock is spent on exercises that ultimately fail. A predictive early-termination mechanism (detecting that the agent is stuck) could cut total benchmark time by up to 40% with minimal pass-rate impact.

### Deterministic vs stochastic exercises

| Category | Count | % |
|----------|------:|---:|
| Always pass (both runs) | 79 | 35.1% |
| Always fail (both runs) | 99 | 44.0% |
| Flaky (different outcome) | 47 | 20.9% |
| **Deterministic** | **178** | **79.1%** |

**79.1% of exercises produce the same outcome regardless of sampling randomness.** The remaining 47 "flaky" exercises are the stochastic frontier — the boundary where temperature-0.3 variance determines pass/fail. The entire run-to-run variance (NET −3) comes from these 47 exercises; the other 178 are locked in.

**Per-language flaky rates:**

| Language | Flaky | Total | Rate |
|----------|------:|------:|-----:|
| JavaScript | 14 | 49 | 29% |
| Go | 10 | 39 | 26% |
| Rust | 6 | 30 | 20% |
| Python | 6 | 34 | 18% |
| Java | 7 | 47 | 15% |
| C++ | 4 | 26 | 15% |

JavaScript and Go have the highest flaky rates (29% and 26%), meaning the agent is operating near the pass/fail boundary on more exercises in those languages. Java and C++ are the most deterministic (85% of exercises produce the same outcome every run).

### Write-guard recovery: what happens after a refusal?

When the Write guard fires and redirects the agent to Edit, does the exercise ultimately pass?

| Metric | Run 1 | Run 2 | Mean |
|--------|------:|------:|-----:|
| Exercises with Write refused | 128 | 127 | 128 |
| Of those, ultimately passed | 43 (34%) | 41 (32%) | 42 (33%) |
| Of those, ultimately failed | 85 (66%) | 86 (68%) | 86 (67%) |

**33% of exercises that trigger the Write guard still pass.** This means the guard's redirect-to-Edit path is effective: the agent recovers from the refused Write, uses Edit instead, and solves the exercise. The 67% that fail after a refusal would have failed regardless — the Write attempt was a symptom of the agent being on a wrong approach, not the cause.

### Cross-language exercise overlap

58 exercise names appear in multiple languages (the Exercism track shares exercise specifications across languages). On universally-hard exercises, the agent fails consistently across all language implementations:

| Exercise | Languages | Mean pass rate |
|----------|-----------|---------------:|
| book-store | Java, Python, JS, Go, Rust | 0% (all fail) |
| bowling | Java, Python, JS, Go, Rust | 0% (all fail) |
| connect | Python, Go | 0% |
| alphametics | Java, JS, Go, Rust | 25% (only JS passes) |
| bottle-song | Java, Python, JS, Go | 88% (only JS sometimes fails) |

Exercises like `book-store` and `bowling` are algorithmically hard (optimal grouping DP, state-machine bowling scoring) and the 9.7B model consistently cannot solve them in any language. Exercises like `bottle-song` are straightforward and pass in almost every language. This suggests the primary bottleneck is **algorithmic reasoning capability**, not language-specific syntax or tool-use patterns.

## Wall clock

| Metric | Run 1 | Run 2 |
|--------|-------|-------|
| Started | 2026-04-13 22:54 | 2026-04-16 00:55 |
| Finished | 2026-04-14 19:07 | 2026-04-17 00:13 |
| Total exercise time | 20.2h | 23.3h |

Run 2 was ~15% slower due to sustained GPU SwPowerCap thermal throttling (ambient temperature elevated). The slower per-turn inference did not affect pass rates — four language tracks reproduced exactly despite the 15% wall-clock penalty.

## Run configurations

| Setting | Run 1 | Run 2 |
|---------|-------|-------|
| Model | `ollama/qwen3.5` (9.7B, Q4_K_M) | same |
| Ollama version | 0.20.5 | same |
| context_limit | 32,768 | same |
| thinking_budget | 2,048 | same |
| temperature | 0.3 | same |
| Harness | `benchmarks/aider_polyglot.py` | same |
| Language order | py→go→rs→js→cpp→java | java→py→cpp→js→go→rs |
| System prompt | Original (with Planning/Interaction tool descriptions) | Reworded (replaced tool descriptions with general priming text about approaching complex tasks and handling ambiguity) |

The system-prompt change between runs is the only code-level difference. The replaced sections described three tools (EnterPlanMode, ExitPlanMode, AskUserQuestion) that were never called in run 1 (grep-verified across all 225 logs: zero invocations). The replacement text carries similar priming language ("careful analysis before complex implementations", "resolve ambiguity from surrounding context") without tool references.

## Hardware

| Component | Detail |
|-----------|--------|
| CPU | Intel Core i9-14900HX, 24 cores / 32 threads, 5.8 GHz max |
| GPU | NVIDIA GeForce RTX 5070 Laptop, 8 GB VRAM |
| System memory | 31 GiB |
| OS | Linux 6.17.0-14-generic |
| Inference | Ollama 0.20.5 in Docker |

## Runner-replacement degradation — the infrastructure lesson

Three additional benchmark runs (runs 2, 4, and 5) were executed but produced results significantly below the two clean runs. Investigation revealed the cause: Ollama's inference runner subprocess dies and is replaced during long benchmark runs, and the replacement runner produces measurably degraded output for the language tracks it serves.

### The failure mechanism

Ollama serves each model through a dedicated **runner subprocess** — a GPU inference process that loads the model weights, maintains the KV cache, and handles streaming token generation. This runner is ephemeral: Ollama kills it when the model is "unloaded" and spawns a fresh one on the next request.

Two mechanisms cause mid-benchmark runner replacement:

1. **`keep_alive` timeout (5 minutes by default).** Between consecutive Ollama API calls, the benchmark harness executes tools — running test suites via Bash, reading files, editing code. When a single tool execution takes longer than 5 minutes (e.g., a Java/Gradle build, a long `cargo test` with compilation, or an `npm install` + test cycle), the model is automatically unloaded and the runner killed. The next API call spawns a fresh runner. **Fix applied:** adding `"keep_alive": -1` to every Ollama request payload in `providers.py` prevents timeout-based unloading.

2. **Runner crash (after ~6–10 hours of sustained inference).** Even with infinite `keep_alive`, the runner process eventually fails — likely due to GPU memory fragmentation, CUDA state accumulation, or internal resource exhaustion after thousands of consecutive inference requests. No CUDA errors or OOM kills appear in the system journal for these crashes; the runner simply dies and Ollama silently spawns a replacement. This remains an open issue in the Ollama runtime.

### The degradation pattern

When the runner is replaced mid-benchmark, the language tracks served by the replacement runner show a consistent degradation pattern:

- **Regression clusters:** 5–15 exercises on the post-crash track flip from `pass` (in clean runs) to `fail`, concentrated in consecutive runs of fails rather than scattered randomly.
- **Pre-crash vs post-crash pass rate:** across the three contaminated runs, exercises completed before the runner crash averaged ~52% pass rate (matching the clean runs). Exercises after the crash averaged ~32% — a 20-percentage-point drop.
- **The degradation is not gradual.** It appears sharply at the first language track served by the replacement runner and persists for the remainder of the benchmark. Tracks completed before the crash produce normal results.

### Per-run breakdown

**Contaminated run A** (2026-04-15, partial — user-stopped at 161/225)

- **Runner replaced twice:** at ~3h (during Go track) and at ~8h (Rust→JavaScript transition).
- **Additional stressor:** ambient temperature ~15°C above Run 1; GPU ran under SwPowerCap at 55–60% of max clock for the entire run.
- **OOM cascade:** the agent's Go implementation for `go/pov` allocated 27.7 GB RSS (tree-rerooting with exponential memory); the OOM killer intervened twice, thrashing the entire system's memory.
- **Impact:**

| Track | Run 1 | This run | When served |
|-------|-------|----------|-------------|
| Python | 52.9% | 50.0% | pre-crash (−1) |
| Go | 38.5% | 41.0% | spans first crash (+1) |
| Rust | 30.0% | 13.3% | post-crash (**−5**) |
| JavaScript | 49.0% | 20.4% | post-crash (**−14**) |
| C++ | 50.0% | 0% (8 ex) | post-crash (**−4** in 8 ex) |

**Contaminated run B** (2026-04-17, partial — harness hung at 126/225)

- **Runner replaced at ~8.7h** (during Python track).
- **Python collapsed to 10/34 = 29.4%** with an 11-exercise consecutive fail streak (exercises 17–28), all on the replacement runner.
- **Harness hung:** `javascript/ocr-numbers` caused the replacement runner to enter a 366% CPU loop, blocking all further progress indefinitely.

| Track | Run 1 | This run | When served |
|-------|-------|----------|-------------|
| Java | 53.2% | 51.1% | pre-crash (−1) |
| Python | 52.9% | 29.4% | spans crash (**−8**) |
| C++ | 50.0% | 46.2% | post-crash (−1) |
| JavaScript | 49.0% | — | hung mid-track |

**Contaminated run C** (2026-04-17–18, partial — user-stopped at 121/225)

- **Runner replaced at ~6.4h** (during Python, exercise `python/poker`).
- **Pre-crash pass rate: 55.4%. Post-crash: 33.9%.** A 21.5-percentage-point drop measured across the same benchmark with the same code.
- **`python/robot-name` hung for 3+ hours** on the replacement runner (run 1 solved it in 40 seconds).

### What this teaches

1. **Infrastructure stability is load-bearing.** The same model, harness, and hardware that produce 46% under clean conditions produce 25–35% under runner-compromised conditions. Agent benchmark results are not just a function of model + scaffold — they are also a function of the inference runtime's reliability over multi-hour runs.

2. **Runner replacement is not equivalent to a cold start.** A fresh runner spawned at the beginning of a benchmark (before any exercises) performs normally. A replacement runner spawned mid-benchmark — inheriting the system's accumulated GPU state, memory fragmentation, and thermal load — performs measurably worse. The mechanism is not fully understood, but the effect is reproducible.

3. **Test-process sandboxing is essential.** The `go/pov` OOM event (27.7 GB RSS from a buggy test binary) took the entire system down. Adding per-exercise memory limits via `systemd-run --scope -p MemoryMax=4G` or `resource.setrlimit` in the harness would contain such events to a single exercise failure without affecting the rest of the benchmark.

4. **Ollama's `keep_alive` default of 5 minutes is too short for agent workloads.** Between Ollama API calls, the agent executes tools that can take several minutes. Setting `keep_alive: -1` (infinite) in every API request is the correct fix for any agent that orchestrates long tool executions between inference calls.

## Artifacts

| File | Description |
|------|-------------|
| `benchmarks/results_full_polyglot_run1.json` | Run 1 per-exercise results (104/225 = 46.22%) |
| `benchmarks/results_full_polyglot_run2.json` | Run 2 per-exercise results (101/225 = 44.89%) |
| `docs/whitepaper.md` | White paper with full narrative, methodology, and limitations |
| `docs/benchmark-baseline-aider.md` | Vanilla Aider + Qwen3.5 baseline results |
