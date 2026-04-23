#!/usr/bin/env bash
# One-shot status for an in-flight harbor (Terminal-Bench 2.0) run.
#
# Usage:
#   benchmarks/harbor_status.sh                             # newest tb2-* dir
#   benchmarks/harbor_status.sh tb2-leaderboard-2026-04-23__10-29-12
#   RUN_ID=foo benchmarks/harbor_status.sh
#
# Prints: process health, completed/remaining, accuracy, rate/ETA,
# passed/failed lists. Harbor's reward lives at
# verifier_result.rewards.reward — that exact path must be used;
# earlier tb_status.sh variants looked at top-level `reward` or
# `parser_results[0].reward` and MISREAD harbor runs as all-failed.
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HB_RUNS="$REPO_ROOT/benchmarks/harbor_runs"

RUN_ID="${1:-${RUN_ID:-}}"
if [ -z "$RUN_ID" ]; then
  RUN_ID=$(find "$HB_RUNS" -maxdepth 1 -mindepth 1 -type d -regextype posix-extended -regex '.*/(tb2|leaderboard|full|harbor)-.*' -printf '%f\n' 2>/dev/null | sort | tail -1)
fi
if [ -z "$RUN_ID" ] || [ ! -d "$HB_RUNS/$RUN_ID" ]; then
  echo "No harbor run dir found (looked in $HB_RUNS)." >&2
  exit 1
fi

DIR="$HB_RUNS/$RUN_ID"

python3 - "$RUN_ID" "$DIR" <<'PY'
import json, os, sys, time, glob, subprocess
run_id, dir_ = sys.argv[1:3]

def sh(cmd):
    try: return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception: return ""
def hm(s):
    if s<=0: return '-'
    h,rem = divmod(int(s),3600); m,_ = divmod(rem,60); return f"{h}h{m:02d}m"

# Total tasks from top-level run config
total = 89  # TB 2.0 default; could read from config.json if present
try:
    rc = json.load(open(os.path.join(dir_, 'result.json')))
    total = rc.get('n_total_trials', total)
except Exception:
    pass

# Per-task results — harbor's reward is at verifier_result.rewards.reward
done, passed, failed = [], [], []
for rp in sorted(glob.glob(os.path.join(dir_, '*/result.json'))):
    try: r = json.load(open(rp))
    except: continue
    vr = (r.get('verifier_result') or {}).get('rewards') or {}
    reward = vr.get('reward')
    if reward is None:
        for v in vr.values():
            if isinstance(v, (int, float)): reward = v; break
    task = os.path.basename(os.path.dirname(rp)).rsplit('__', 1)[0]
    done.append(task)
    (passed if (reward is not None and reward >= 1.0) else failed).append((task, reward))

rem = max(total - len(done), 0)
# Process
run_pid = sh(f"pgrep -af 'harbor run.*{run_id}' | awk '{{print $1}}' | head -1")
elapsed = sh(f"ps -p {run_pid} -o etime= 2>/dev/null").strip() if run_pid else "(dead)"
elapsed_s = 0
if elapsed and ":" in elapsed:
    parts = elapsed.split('-'); days = int(parts[0]) if len(parts)==2 else 0
    hms = parts[-1].split(':')
    if len(hms)==3: elapsed_s = days*86400 + int(hms[0])*3600 + int(hms[1])*60 + int(hms[2])
    elif len(hms)==2: elapsed_s = days*86400 + int(hms[0])*60 + int(hms[1])
rate = (elapsed_s/len(done)) if done else 0
eta = rate * rem
acc = 100*len(passed)/len(done) if done else 0

# In-flight
trial_dirs = sorted([p for p in glob.glob(f'{dir_}/*/') if os.path.isdir(p)], key=lambda p: os.path.getmtime(p), reverse=True)
in_flight_task, in_flight_age = None, None
for td in trial_dirs:
    if not os.path.exists(td+'result.json'):
        in_flight_task = os.path.basename(td.rstrip('/')).rsplit('__',1)[0]
        in_flight_age = int(time.time() - os.path.getmtime(td))
        break

print(f"run_id     : {run_id}")
print(f"dataset    : terminal-bench@2.0")
print(f"process    : pid={run_pid or 'DEAD'}  elapsed={elapsed}")
print(f"progress   : {len(done)}/{total} done  ({rem} remaining)")
print(f"accuracy   : {len(passed)}/{len(done)} = {acc:.1f} %  {'⚠ early-sample' if len(done)<10 else ''}")
print(f"rate       : {hm(rate)} / task  →  ETA +{hm(eta)} remaining")
if in_flight_task:
    print(f"in-flight  : {in_flight_task}  (last-touched {in_flight_age}s ago)")

if passed:
    print(f"\npassed ({len(passed)}):")
    for t, _ in passed[-15:]:
        print(f"  ✓ {t}")
    if len(passed) > 15: print(f"  (+{len(passed)-15} earlier)")
if failed:
    print(f"\nfailed ({len(failed)}):")
    for t, rv in failed[-15:]:
        print(f"  ✗ {t}  (reward={rv})")
    if len(failed) > 15: print(f"  (+{len(failed)-15} earlier)")
PY
