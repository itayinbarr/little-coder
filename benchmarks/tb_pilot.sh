#!/usr/bin/env bash
# Convenience wrapper for running Terminal-Bench tasks through the
# little-coder-pi adapter. Used for pilot runs where we run one or a few
# tasks at a time and inspect the trajectory between runs.
#
# Usage:
#   benchmarks/tb_pilot.sh hello-world
#   benchmarks/tb_pilot.sh hello-world fix-permissions broken-networking
#   TBENCH_ROOT=/custom/path benchmarks/tb_pilot.sh my-task
#
# Env:
#   TB_LITTLE_CODER_MODEL  — overrides the model (default: llamacpp/qwen3.6-35b-a3b)
#   TBENCH_ROOT            — terminal-bench checkout (default: ~/Documents/terminal-bench)
#   TB_DATASET_SUBDIR      — tasks/ vs original-tasks/ (default: original-tasks)
#
# Requires: docker access. If $USER isn't in the docker group we fall back
# to `sg docker -c ...` automatically.
set -euo pipefail

MODEL="${TB_LITTLE_CODER_MODEL:-llamacpp/qwen3.6-35b-a3b}"
ROOT="${TBENCH_ROOT:-$HOME/Documents/terminal-bench}"
SUBDIR="${TB_DATASET_SUBDIR:-original-tasks}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO_ROOT/benchmarks/tb_runs"

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 <task-id> [<task-id> ...]" >&2
  exit 1
fi

TASK_FLAGS=()
for t in "$@"; do
  TASK_FLAGS+=(--task-id "$t")
done

export TB_LITTLE_CODER_MODEL="$MODEL"
# llama.cpp / ollama client keys for pi (accept any string; llama.cpp ignores them)
export LLAMACPP_API_KEY="${LLAMACPP_API_KEY:-noop}"
export OLLAMA_API_KEY="${OLLAMA_API_KEY:-noop}"

echo "model:   $MODEL"
echo "dataset: $ROOT/$SUBDIR"
echo "tasks:   $*"
echo "output:  $OUT"
echo

TB_CMD=(tb run
  --dataset-path "$ROOT/$SUBDIR"
  "${TASK_FLAGS[@]}"
  --agent-import-path benchmarks.tb_adapter.little_coder_agent:LittleCoderAgent
  --output-path "$OUT"
  --n-concurrent 1
  --no-cleanup)

# Run with docker access — prefer direct if the user is in the docker group,
# fall back to `sg docker -c` otherwise.
if groups | grep -q '\bdocker\b'; then
  cd "$REPO_ROOT" && "${TB_CMD[@]}"
else
  # Re-quote each arg through sg's `-c` string
  printf -v CMD_STR '%q ' "${TB_CMD[@]}"
  sg docker -c "cd '$REPO_ROOT' && $CMD_STR"
fi
