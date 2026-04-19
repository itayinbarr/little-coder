#!/usr/bin/env bash
# Baseline: vanilla Aider + Qwen3.5:latest (9B Q4_K_M) on full polyglot (225 exercises).
# Two phases:
#   phase1: 104 exercises that passed in little-coder run 1 (most informative)
#   phase2: the remaining 121 exercises
#
# Matched context with little-coder: --num-ctx 32768.
# Aider harness patched for native (non-docker) JS/CPP test runners.
#
# Hardware: single RTX 5070 Laptop 8 GB. Do NOT run while another Qwen3.5
# workload is active — GPU is saturated.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
AIDER_SRC="$HERE/aider-src"
VENV_BIN="$HERE/venv/bin"
BENCH_ROOT="$HERE/tmp.benchmarks"
SETTINGS="$HERE/model-settings.yml"
LOG="$HERE/run_baseline.log"

mkdir -p "$BENCH_ROOT"

if [[ -n "${WAIT_PID:-}" ]]; then
  echo "[$(date -Is)] waiting for PID $WAIT_PID before starting baseline" | tee -a "$LOG"
  tail --pid="$WAIT_PID" -f /dev/null
  sleep 30
fi

echo "[$(date -Is)] GPU state:" | tee -a "$LOG"
nvidia-smi --query-gpu=memory.used,memory.free --format=csv | tee -a "$LOG" || true

export OLLAMA_API_BASE="http://localhost:11434"
export AIDER_BENCHMARK_DIR="$BENCH_ROOT"
export AIDER_DOCKER=1
export NPM_INSTALL="$HERE/npm-install"
# Per-exercise wall-clock cap (seconds). Enforced inside benchmark.py via SIGALRM:
# on overrun, the exercise is marked failed with exceeded_wall_cap=true and the run moves on.
export AIDER_PER_EXERCISE_CAP_SECONDS="${AIDER_PER_EXERCISE_CAP_SECONDS:-3600}"

run_phase() {
  local phase="$1"
  local tree="$HERE/${phase}-tree"
  local name="qwen35-vanilla-aider-${phase}"
  # Resume if a prior dir for this phase exists (killed mid-run); else start fresh.
  # Aider's --cont uses find_latest_benchmark_dir which picks the newest date-stamped dir;
  # safe because phases run sequentially and each phase only has one active dir at a time.
  local mode="--new"
  if compgen -G "$BENCH_ROOT/*--${name}" > /dev/null; then
    mode="--cont"
    echo "[$(date -Is)] === resuming $phase (existing dir found) ===" | tee -a "$LOG"
  else
    echo "[$(date -Is)] === launching $phase ===" | tee -a "$LOG"
  fi
  cd "$AIDER_SRC"
  "$VENV_BIN/python" benchmark/benchmark.py "$name" \
    $mode \
    --model ollama_chat/qwen3.5 \
    --exercises-dir "$tree" \
    --languages cpp,go,java,javascript,python,rust \
    --tries 2 \
    --threads 1 \
    --num-ctx 32768 \
    --read-model-settings "$SETTINGS" \
    --num-tests -1 \
    2>&1 | tee -a "$LOG"
  echo "[$(date -Is)] === $phase done ===" | tee -a "$LOG"
}

run_phase phase1
run_phase phase2

echo "[$(date -Is)] baseline complete; results under $BENCH_ROOT" | tee -a "$LOG"
