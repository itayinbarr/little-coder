#!/usr/bin/env python3
"""Human-readable status dashboard for a running polyglot benchmark.

Designed to be safe to call at any time without touching the running
harness. Reads benchmarks/results_full_polyglot.json (which the harness
atomic-flushes after every exercise and every attempt) and prints
everything you would want to know in one invocation:

  - per-language progress bars with pass/fail counts
  - overall progress + pct + rate + ETA
  - currently-in-flight exercise (lang/name/attempt/elapsed)
  - most recent N completed exercises with outcome + time + tools
  - aggregate tool-use stats across all completed exercises
  - all failures with first-error lines
  - Write-refusal count (how often the tool-level guard fired)
  - liveness warning if nothing has flushed in >30 min

Usage:
    python benchmarks/polyglot_status.py [path/to/results_full_polyglot.json]
"""
import sys
import json
import datetime
from pathlib import Path
from collections import Counter

LANG_ORDER = ["python", "go", "rust", "javascript", "cpp", "java"]
RECENT_N = 8  # how many most-recent exercises to list


def _fmt_bar(done: int, total: int, width: int = 30) -> str:
    if total == 0:
        return "[" + " " * width + "]"
    filled = int(round(width * done / total))
    return "[" + "█" * filled + "·" * (width - filled) + "]"


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def _parse_iso(s: str) -> datetime.datetime:
    try:
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return datetime.datetime.now()


def _status_marker(status: str) -> str:
    return {
        "pass_1": "✓1",
        "pass_2": "✓2",
        "fail":   "✗ ",
    }.get(status, "? ")


def main() -> int:
    default_path = Path(__file__).parent / "results_full_polyglot.json"
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_path
    if not path.exists():
        print(f"ERROR: results file not found: {path}")
        return 1

    try:
        data = json.loads(path.read_text())
    except Exception as e:
        # Atomic write in progress — re-read with a retry is unnecessary
        # since the harness uses os.replace; this only fires on genuine
        # corruption, which we just report.
        print(f"ERROR: could not parse {path}: {e}")
        return 1

    started = _parse_iso(data.get("started_at", ""))
    updated = _parse_iso(data.get("updated_at", ""))
    now = datetime.datetime.now()

    overall = data.get("overall", {})
    total = overall.get("total", 0)
    done = overall.get("done", 0)
    passed = overall.get("passed", 0)
    pct = overall.get("pct", 0.0)

    elapsed_s = (updated - started).total_seconds() if done else 0.0
    staleness_s = (now - updated).total_seconds()
    rate_per_s = done / elapsed_s if elapsed_s > 0 and done > 0 else 0.0
    remaining = total - done
    eta_s = remaining / rate_per_s if rate_per_s > 0 else 0.0
    wallclock_finish = (now + datetime.timedelta(seconds=eta_s)) if rate_per_s > 0 else None

    model = data.get("model", "?")
    started_str = started.strftime("%Y-%m-%d %H:%M:%S")

    print()
    print("=" * 78)
    print(f"  Aider Polyglot — {model}")
    print(f"  Started: {started_str}   Elapsed: {_fmt_duration(elapsed_s)}"
          f"   Last flush: {_fmt_duration(staleness_s)} ago")
    print("=" * 78)

    # Per-language rows
    for lang_name in LANG_ORDER:
        l = data.get("languages", {}).get(lang_name)
        if l is None:
            continue
        ltotal = l.get("total", 0)
        ldone = l.get("done", 0)
        lpass = l.get("pass_1", 0) + l.get("pass_2", 0)
        lfail = l.get("fail", 0)
        lpct = (100 * lpass / ldone) if ldone else 0.0
        bar = _fmt_bar(ldone, ltotal)
        print(f"  {lang_name:<11} {bar} {ldone:>3}/{ltotal:<3} "
              f"pass={lpass:<3} fail={lfail:<3} {lpct:5.1f}%")

    print("-" * 78)
    bar = _fmt_bar(done, total)
    print(f"  {'OVERALL':<11} {bar} {done:>3}/{total:<3} "
          f"pass={passed:<3} {pct:5.2f}%")

    # Rate + ETA
    if rate_per_s > 0:
        print()
        print(f"  Rate: {rate_per_s * 60:.2f} exercises/min  "
              f"({_fmt_duration(1 / rate_per_s)} per exercise)")
        print(f"  ETA:  {_fmt_duration(eta_s)} remaining  "
              f"(finish ≈ {wallclock_finish.strftime('%Y-%m-%d %H:%M')})")
    else:
        print()
        print("  Rate: insufficient data for ETA")

    # Currently in-flight exercise
    current = data.get("current")
    if current:
        cur_started = _parse_iso(current.get("started_at", ""))
        cur_elapsed = (now - cur_started).total_seconds()
        attempt = current.get("attempt", 1)
        attempt_label = "1st" if attempt == 1 else "2nd"
        print()
        print(f"  IN FLIGHT → {current.get('lang')}/{current.get('name')}  "
              f"({attempt_label} attempt, {_fmt_duration(cur_elapsed)} so far)")
    elif done < total:
        print()
        print("  IN FLIGHT → (between exercises)")

    # Gather all completed details across languages for cross-cutting stats
    all_details: list = []
    for lang_name in LANG_ORDER:
        l = data.get("languages", {}).get(lang_name, {})
        for d in l.get("details", []):
            all_details.append((lang_name, d))

    # Most recent N completed
    if all_details:
        print()
        print(f"  Recent {min(RECENT_N, len(all_details))} completed:")
        for lang_name, d in all_details[-RECENT_N:]:
            marker = _status_marker(d.get("status", ""))
            time_s = d.get("time", 0)
            tools = d.get("tools", {})
            tool_summary = " ".join(f"{k}×{v}" for k, v in sorted(tools.items())) if tools else ""
            refused = d.get("write_refusals", 0)
            refused_note = f"  [Write refused×{refused}]" if refused else ""
            print(f"    {marker}  {lang_name:<10} {d.get('name', ''):<24} "
                  f"{time_s:>6.0f}s  {tool_summary}{refused_note}")

    # Aggregate tool usage
    if all_details:
        tool_totals: Counter = Counter()
        refusal_total = 0
        time_passes: list = []
        time_fails: list = []
        for _lang, d in all_details:
            for k, v in d.get("tools", {}).items():
                tool_totals[k] += v
            refusal_total += d.get("write_refusals", 0)
            if d.get("status", "").startswith("pass"):
                time_passes.append(d.get("time", 0))
            elif d.get("status") == "fail":
                time_fails.append(d.get("time", 0))

        print()
        print(f"  Aggregate tool usage across {len(all_details)} completed exercises:")
        for name in ["Write", "Edit", "Read", "Bash", "Glob", "Grep", "WebFetch", "Agent"]:
            count = tool_totals.get(name, 0)
            if count:
                avg = count / len(all_details)
                print(f"    {name:<9} {count:>5}  ({avg:.1f} / exercise)")
        if refusal_total:
            print(f"    Write refused by tool guard: {refusal_total} "
                  f"({refusal_total / len(all_details):.2f} / exercise)")

        if time_passes:
            avg_pass = sum(time_passes) / len(time_passes)
            print(f"  Avg time (pass): {avg_pass:.0f}s across {len(time_passes)} passes")
        if time_fails:
            avg_fail = sum(time_fails) / len(time_fails)
            print(f"  Avg time (fail): {avg_fail:.0f}s across {len(time_fails)} fails")

    # Failure digest
    failures = [(ln, d) for ln, d in all_details if d.get("status") == "fail"]
    if failures:
        print()
        print(f"  Failures ({len(failures)}):")
        for lang_name, d in failures:
            err = d.get("first_error", "")
            if len(err) > 80:
                err = err[:77] + "..."
            print(f"    ✗  {lang_name:<10} {d.get('name', ''):<24} {err}")

    # Liveness warning
    if done < total and staleness_s > 1800:
        print()
        print(f"  ⚠  No flush in {_fmt_duration(staleness_s)} — run may be wedged. "
              f"Check `tail benchmarks/full_polyglot_logs/run.log`.")

    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
