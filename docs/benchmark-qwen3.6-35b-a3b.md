# Aider Polyglot Benchmark — Qwen3.6-35B-A3B Run

One complete end-to-end run of the full 225-exercise Aider Polyglot benchmark with `little-coder + llamacpp/qwen3.6-35b-a3b` (Qwen3.6-35B-A3B, 35B total / 3B active MoE, `unsloth/Qwen3.6-35B-A3B-GGUF UD-Q4_K_M`, ~22.1 GB). Executed on the same hardware and same harness as the prior [`ollama/qwen3.5` two-run reproduction](benchmark-reproduction.md), with llama.cpp replacing Ollama as the serving backend.

## Headline

```
Run 3 (Qwen3.6-35B-A3B):   177 / 225 = 78.67%
Run 2 (Qwen3.5 9B):        101 / 225 = 44.89%
Run 1 (Qwen3.5 9B):        104 / 225 = 46.22%

Run3 − mean(Run1,Run2):   +33.1 pp
```

This places the little-coder agent well inside the public Aider Polyglot leaderboard's top-10 band. The entire run was offline on an 8 GB VRAM laptop GPU — no network calls, no cloud model.

## Setup

| Component | Value |
|---|---|
| Model | Qwen3.6-35B-A3B, `unsloth/...-UD-Q4_K_M.gguf`, 22.1 GB on disk |
| Serving | `llama.cpp` built from source (CUDA 13.1, sm_120 / Blackwell) |
| Flags | `-ngl 99 --n-cpu-moe 999 --flash-attn on --jinja -c 32768 -t 16` |
| GPU | RTX 5070 Laptop, 8 GB VRAM |
| CPU / RAM | Intel i9-14900HX / 32 GB DDR5 |
| Agent | little-coder v0.0.4, `small-model optimizations: ON`, `deliberation_mode: on_failure` |
| Context cap | 16 384 tokens for the first 5 exercises, then **32 768** for the remaining 220 (restart with `--resume`; the `bowling` record from the 16 K period was discarded and re-run under 32 K for fairness) |
| Started | 2026-04-21T10:03 (initial 16 K) → 2026-04-21T11:25 (32 K restart) |
| Finished | 2026-04-22T13:52 |
| Cumulative wall-clock | ~26.8 h (sum of per-exercise times) |

The `--n-cpu-moe 999` flag is the key VRAM trick: Qwen3.6-35B-A3B's expert weights sit in RAM, only attention + shared expert occupy VRAM. Result: 3.8 GB VRAM used at 32 K context, with ~4 GB of headroom for longer context if needed.

## Per-language pass rates

| Language   | N  | Qwen3.6-35B-A3B | Qwen3.5 9B R1 | Qwen3.5 9B R2 | Δ vs mean |
|------------|---:|-----------------|---------------|---------------|----------:|
| JavaScript | 49 | 44 (**89.8 %**) | 24 (49.0 %)   | 22 (44.9 %)   | **+42.8 pp** |
| Python     | 34 | 30 (**88.2 %**) | 18 (52.9 %)   | 18 (52.9 %)   | **+35.3 pp** |
| C++        | 26 | 22 (**84.6 %**) | 13 (50.0 %)   | 13 (50.0 %)   | **+34.6 pp** |
| Java       | 47 | 36 (**76.6 %**) | 25 (53.2 %)   | 24 (51.1 %)   | **+24.5 pp** |
| Go         | 39 | 29 (**74.4 %**) | 15 (38.5 %)   | 15 (38.5 %)   | **+35.9 pp** |
| Rust       | 30 | 16 (**53.3 %**) |  9 (30.0 %)   |  9 (30.0 %)   | **+23.3 pp** |
| **Total**  | **225** | **177 (78.7 %)** | **104 (46.2 %)** | **101 (44.9 %)** | **+33.1 pp** |

Every language improved; the smallest delta (Rust, +23.3 pp) still beats the largest Qwen3.5 gain (Java R1, 53.2 %) by a wide margin. Rust remains the hardest track (more type-system friction per iteration) but the absolute number rose from 9 to 16.

## First-attempt vs second-attempt passes

| Language   | 1st (p1) | 2nd (p2) | Fail | Retry recovery rate |
|------------|---------:|---------:|-----:|--------------------:|
| Python     | 29       | 1        | 4    | 20 % |
| Go         | 24       | 5        | 10   | 33 % |
| Rust       | 9        | 7        | 14   | 33 % |
| JavaScript | 39       | 5        | 5    | 50 % |
| C++        | 21       | 1        | 4    | 20 % |
| Java       | 36       | 0        | 11   | 0 % |
| **Total**  | **158**  | **19**   | **48** | **28 %** |

"Retry recovery rate" = pass_2 / (pass_2 + fail) — of the exercises the agent didn't solve on the first try, the fraction the retry path saved. JavaScript's 50 % and Go/Rust's 33 % suggest the test-output-as-context mechanism is meaningful on those stacks; Java is an outlier at 0 % (once a Java task failed the first try, none of them came back — consistent with Java's verbose test output eating retry context).

## Exercise outcome stability vs R1 and R2

Of the 225 exercises, outcome stability relative to BOTH Qwen3.5 runs:

| Category                                  | Count | %     |
|-------------------------------------------|------:|------:|
| Same pass in all three runs               | 52    | 23.1 % |
| Passed in all three, different attempt    | 23    | 10.2 % |
| Same fail in all three                    | 36    | 16.0 % |
| **Fail → Pass** vs both R1 and R2         | **63** | **28.0 %** |
| **Pass → Fail** vs both R1 and R2         | **4**  | **1.8 %**  |
| Split (one historical run disagrees)      | 47    | 20.9 % |

**The progression is net +59 exercises.** 63 exercises flipped from fail-in-both-historical to pass; only 4 regressed in the same sense. That is a ~16 : 1 progression-to-regression ratio — the improvement is systematic, not a single lucky run.

The 4 clean regressions: `go/connect`, `javascript/state-of-tic-tac-toe`, `python/transpose`, `rust/robot-name`. In each case the model produced functionally reasonable code that failed on exact output matching (robot-name regex assertion, state-of-tic-tac-toe enum value, etc.) — the kind of thing a single retry with tighter prompting would likely fix.

## Persistent cross-language failures

Exercises that failed in 2 or more languages in this run:

| Exercise        | Languages that failed                            |
|-----------------|--------------------------------------------------|
| **bowling**     | Python, Go, Rust, JavaScript, Java **(all 5 tried)** |
| forth           | Go, Rust, JavaScript                             |
| react           | Rust, JavaScript, Java                           |
| alphametics     | Go, Rust                                         |
| scale-generator | Go, Rust                                         |
| transpose       | Python, Go                                       |
| two-bucket      | Python, Java                                     |

`bowling` is the clean outlier — it failed in every language tried, across all three runs. The pattern is consistent: the agent writes the scoring logic correctly, then the 10th-frame special-case validation (bonus rolls, strike-plus-spare combinations) exceeds the turn budget before it converges. Not a language-specific issue; a model+agent limitation on long-chain state-machine reasoning.

## Tool-use and timing (per-exercise averages)

| Language   | Mean turns | Mean time | s / turn | Median time |
|------------|-----------:|----------:|---------:|------------:|
| C++        | 13.0       | 2.9 min   | 13       | 2.1 min |
| Python     | 9.4        | 6.0 min   | 38       | 1.8 min |
| JavaScript | 12.1       | 6.8 min   | 34       | 2.9 min |
| Go         | 13.4       | 7.2 min   | 32       | 3.0 min |
| Rust       | 16.3       | 8.4 min   | 31       | 5.2 min |
| Java       | 11.4       | 9.8 min   | 52       | 3.0 min |

The model generated at a sustained ~38 tokens/second during the run. Median times are much lower than means — most exercises finish in 2–3 minutes, but a long-tail of complex exercises (Rust especially) burn 15+ min each.

## Comparison summary

```
                    Qwen3.5 9B mean    Qwen3.6-35B-A3B    Δ
overall pass rate   45.6 %             78.7 %             +33.1 pp
1st-attempt pass    37.6 %             70.2 %             +32.6 pp
retry pass          8.0 %              8.4 %              +0.4 pp
```

Nearly all of the gain came from **first-attempt** passes. The retry rate was already close to its ceiling under Qwen3.5 (most exercises that get saved by retry get saved regardless of base model); the dramatic improvement is in exercises the 35B solves outright on the first try.

## Reproducing

```bash
# 1. Serve the model (launch script from the main README)
~/tools/llama.cpp/run/qwen36-a3b.sh

# 2. Run the full benchmark
cd ~/Documents/local-coder
python benchmarks/aider_polyglot.py llamacpp/qwen3.6-35b-a3b --resume
```

Results stream into `benchmarks/results_full_polyglot.json` atomically per exercise; interrupt and `--resume` at any point. The canonical result file for this run is [`benchmarks/results_full_polyglot_run3.json`](../benchmarks/results_full_polyglot_run3.json).

## Files

- Raw per-exercise results: [`benchmarks/results_full_polyglot_run3.json`](../benchmarks/results_full_polyglot_run3.json)
- Historical runs (Qwen3.5 9B): [`benchmarks/results_full_polyglot_run1.json`](../benchmarks/results_full_polyglot_run1.json), [`benchmarks/results_full_polyglot_run2.json`](../benchmarks/results_full_polyglot_run2.json)
- Prior two-run reproduction write-up: [`docs/benchmark-reproduction.md`](benchmark-reproduction.md)
