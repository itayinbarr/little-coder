#!/usr/bin/env bash
# One-liner status for an in-flight Terminal-Bench run.
#
# Usage:
#   benchmarks/tb_status.sh                             # uses RUN_ID env or newest leaderboard-* dir
#   benchmarks/tb_status.sh leaderboard-2026-04-22__22-50-08
#   RUN_ID=foo benchmarks/tb_status.sh
#
# Prints: process health, docker in-flight, completed/remaining, accuracy,
# last results, per-minute rate, ETA, failed task list (if any).
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TB_RUNS="$REPO_ROOT/benchmarks/tb_runs"

RUN_ID="${1:-${RUN_ID:-}}"
if [ -z "$RUN_ID" ]; then
  # Pick newest dir only (skip .log files and non-dirs)
  RUN_ID=$(find "$TB_RUNS" -maxdepth 1 -mindepth 1 -type d -regextype posix-extended -regex '.*/(leaderboard|full)-[0-9].*' -printf '%f\n' 2>/dev/null | sort | tail -1)
fi
if [ -z "$RUN_ID" ] || [ ! -d "$TB_RUNS/$RUN_ID" ]; then
  echo "No run dir found (looked in $TB_RUNS)." >&2
  exit 1
fi

DIR="$TB_RUNS/$RUN_ID"
META="$DIR/run_metadata.json"
RES="$DIR/results.json"

python3 - "$RUN_ID" "$DIR" "$META" "$RES" <<'PY'
import json, os, sys, time, subprocess, datetime
run_id, dir_, meta_p, res_p = sys.argv[1:5]

def sh(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""

# ── Metadata
total = 0
dataset = ""
if os.path.exists(meta_p):
    m = json.load(open(meta_p))
    total = len(m.get("task_ids", []))
    dataset = f"{m.get('dataset_name')}@{m.get('dataset_version')}"

# ── Results
n_resolved = n_unresolved = 0
resolved = unresolved = []
per_task = []
if os.path.exists(res_p):
    r = json.load(open(res_p))
    n_resolved = r.get("n_resolved", 0)
    n_unresolved = r.get("n_unresolved", 0)
    resolved = r.get("resolved_ids", []) or []
    unresolved = r.get("unresolved_ids", []) or []
    per_task = r.get("results", []) or []
done = n_resolved + n_unresolved
remaining = max(total - done, 0)
acc = (n_resolved / done * 100.0) if done else 0.0

# ── Trial subdirs (includes in-progress task not yet in results.json)
trial_dirs = [d for d in os.listdir(dir_) if os.path.isdir(os.path.join(dir_, d))]

# ── Process state
run_pid = sh(f"pgrep -af 'tb run.*{run_id}' | awk '{{print $1}}' | head -1")
elapsed = sh(f"ps -p {run_pid} -o etime= 2>/dev/null").strip() if run_pid else "(not running)"
elapsed_s = 0
if elapsed and ":" in elapsed:
    parts = elapsed.split("-")
    days = int(parts[0]) if len(parts) == 2 else 0
    hms = parts[-1].split(":")
    if len(hms) == 3:
        elapsed_s = days*86400 + int(hms[0])*3600 + int(hms[1])*60 + int(hms[2])
    elif len(hms) == 2:
        elapsed_s = days*86400 + int(hms[0])*60 + int(hms[1])

# ── Docker in-flight
in_flight = sh(f"sg docker -c \"docker ps --filter 'name={run_id}' --format '{{{{.Names}}}}  up {{{{.Status}}}}'\"")

# ── Rate / ETA
rate_s_per_task = (elapsed_s / done) if (done and elapsed_s) else 0
eta_s = rate_s_per_task * remaining
def humanize(s):
    if s <= 0: return "-"
    h, rem = divmod(int(s), 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h{m:02d}m"

# ── Print
print(f"run_id     : {run_id}")
print(f"dataset    : {dataset}")
print(f"process    : pid={run_pid or 'DEAD'}  elapsed={elapsed}")
print(f"progress   : {done}/{total} done  ({remaining} remaining)  in-progress-dirs={len(trial_dirs) - done}")
print(f"accuracy   : {n_resolved}/{done} = {acc:.1f} %  {'⚠ early-sample' if done < 10 else ''}")
print(f"rate       : {humanize(rate_s_per_task)} / task  →  ETA +{humanize(eta_s)} remaining")
if in_flight:
    print(f"in-flight  : {in_flight}")
else:
    print(f"in-flight  : (no container — between tasks)")

if resolved:
    print(f"\npassed ({len(resolved)}):")
    for t in resolved[-10:]:
        print(f"  ✓ {t}")
    if len(resolved) > 10:
        print(f"  ... and {len(resolved) - 10} more above")
if unresolved:
    print(f"\nfailed ({len(unresolved)}):")
    for t in unresolved[-10:]:
        print(f"  ✗ {t}")
    if len(unresolved) > 10:
        print(f"  ... and {len(unresolved) - 10} more above")

# ── Last-modified trial dir (probably in-progress task)
try:
    trial_paths = [(os.path.getmtime(os.path.join(dir_, d)), d) for d in trial_dirs]
    trial_paths.sort(reverse=True)
    if trial_paths and not any(d == trial_paths[0][1] for d in resolved + unresolved):
        age = int(time.time() - trial_paths[0][0])
        print(f"\ncurrent    : {trial_paths[0][1]} (last-modified {age}s ago)")
except Exception:
    pass

PY
