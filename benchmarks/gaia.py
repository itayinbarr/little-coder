#!/usr/bin/env python3
"""GAIA runner for little-coder.

Drives `pi --mode rpc` per task via benchmarks/rpc_client.py::PiRpc, with
the GAIA-shaped tool allow-list (Browser*, Evidence*, WebFetch, WebSearch,
Read/Bash/Grep/Glob — no Write/Edit, GAIA tasks don't need code edits).

Output layout (per run):
    benchmarks/gaia_runs/<run_name>/
        manifest.json           ← run config
        results.json            ← full results, one entry per task_id
        submission.jsonl        ← leaderboard-shaped {task_id, model_answer, reasoning_trace}
        <task_id>/
            prompt.txt          ← exact prompt sent to pi
            transcript.txt      ← assistant text, end-of-prompt
            tool_calls.jsonl    ← one JSON per tool call
            notifications.txt   ← skill/knowledge/quality-monitor events
            stderr.log
            result.json         ← {model_answer, gold (val only), correct, elapsed_s}

Usage:
    # Pilot — pick by task_id (validation set, public answers)
    python benchmarks/gaia.py --split validation \\
        --task-ids c61d22de-5f6c-4958-a7f6-5e9707bd3466 \\
                   17b5a6a3-bc87-42e8-b0fb-6ab0781ef2cc

    # Full validation (165 tasks across L1/L2/L3)
    python benchmarks/gaia.py --split validation --all

    # Full test (no scoring — produces submission.jsonl for upload)
    python benchmarks/gaia.py --split test --all
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rpc_client import PiRpc  # noqa: E402
from gaia_scorer import score, extract_final_answer  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = Path(__file__).parent / "gaia_runs"
DEFAULT_MODEL = "llamacpp/qwen3.6-35b-a3b"

# GAIA-shaped tool allow-list. Mirrors the whitepaper / ALLOWED_TOOLS in
# the v0.0.x Python harness. Both lower- and Capitalized variants are
# included because pi's tool-gating extension matches by exact name and
# different extensions register slightly different casings.
ALLOWED_TOOLS = [
    # File reads (no Write/Edit — GAIA doesn't ask the agent to author code)
    "read", "Read",
    "glob", "Glob",
    "grep", "Grep",
    # Shell — used for processing attachments (PDF, audio, image -> python)
    "bash", "Bash",
    # Web research surface
    "webfetch", "WebFetch",
    "websearch", "WebSearch",
    # Browser surface (Playwright extension)
    "BrowserNavigate", "BrowserClick", "BrowserType",
    "BrowserScroll", "BrowserExtract", "BrowserBack", "BrowserHistory",
    # Evidence surface
    "EvidenceAdd", "EvidenceGet", "EvidenceList",
]


# ── Dataset loading ────────────────────────────────────────────────────────

def _hf_cached_path(repo_id: str = "gaia-benchmark/GAIA") -> Path:
    """Return the local snapshot path. Triggers download on first call."""
    from huggingface_hub import snapshot_download
    return Path(snapshot_download(repo_id=repo_id, repo_type="dataset"))


def _load_split(year: str, level_or_all: str | None, split: str) -> tuple[list[dict], Path]:
    """Load a GAIA split and return (records, dataset_root).

    Reads the parquet metadata files shipped alongside the gated repo.
    Layout: <root>/<year>/<split>/metadata{,.level1,.level2,.level3}.parquet
    """
    import pyarrow.parquet as pq
    root = _hf_cached_path()
    base = root / year / split

    if level_or_all is None:
        candidate = base / "metadata.parquet"
    else:
        # "level1" -> "metadata.level1.parquet"
        candidate = base / f"metadata.{level_or_all}.parquet"
    if not candidate.exists():
        raise FileNotFoundError(f"GAIA metadata not found at {candidate}")
    table = pq.read_table(candidate)
    records = table.to_pylist()
    # Test split has empty "Final answer" — that's expected; gold is hidden.
    return records, root


# ── Per-task execution ─────────────────────────────────────────────────────

def _build_prompt(task: dict, attachment_dir: Path | None) -> str:
    question = task.get("Question") or task.get("question") or ""
    file_name = task.get("file_name") or ""
    parts = [
        "You are solving a GAIA research question. Find the answer using your tools.",
        "",
        f"Question:\n{question}",
    ]
    if file_name and attachment_dir is not None:
        attach = attachment_dir / file_name
        if attach.exists():
            parts.append("")
            parts.append(f"Attachment available at: {attach}")
            parts.append("Use Bash + standard libs (pandas, openpyxl, pypdf, ffmpeg, etc.) to read it.")
    parts += [
        "",
        "Process:",
        "1. Decompose the question into 1–2 unknowns.",
        "2. Use BrowserNavigate + BrowserExtract (or WebSearch for first hops) to gather facts.",
        "3. Save each citable fact via EvidenceAdd before relying on it.",
        "4. Before answering: call EvidenceList; every claim in your answer must trace to an id.",
        "",
        "Output rule: end your final reply with a single line:",
        "  Answer: <value>",
        "Do NOT append further prose after that line. Numbers should be plain digits without units unless the",
        "question explicitly asks for them. Lists are comma-separated.",
    ]
    return "\n".join(parts)


def _stage_attachment(task: dict, dataset_root: Path, work: Path) -> Path | None:
    """If task has a file, copy it into `work` so the agent can read it."""
    file_path = task.get("file_path") or ""
    file_name = task.get("file_name") or ""
    if not file_path or not file_name:
        return None
    src = dataset_root / file_path
    if not src.exists():
        # Some metadata uses absolute paths under the dataset root
        alt = dataset_root / Path(file_path).name
        if alt.exists():
            src = alt
        else:
            return None
    dst = work / file_name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return work


def _run_task(
    task: dict,
    model: str,
    out_dir: Path,
    dataset_root: Path,
    timeout: int,
    score_against_gold: bool,
) -> dict:
    task_id = task["task_id"]
    task_dir = out_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"gaia-{task_id[:8]}-") as tmp:
        work = Path(tmp)
        _stage_attachment(task, dataset_root, work)
        prompt = _build_prompt(task, work)
        (task_dir / "prompt.txt").write_text(prompt)

        t0 = time.time()
        text_out = ""
        tool_calls: list[dict] = []
        notifications: list[dict] = []
        turn_count = 0
        compactions = 0
        agent_ended = False
        stop_reason = ""
        stderr = ""
        agent_error = ""

        try:
            with PiRpc(
                model=model,
                cwd=str(work),
                benchmark="gaia",
                allowed_tools=ALLOWED_TOOLS,
                session_id=f"gaia-{task_id[:10]}",
                env={"LITTLE_CODER_PERMISSION_MODE": "accept-all"},
            ) as rpc:
                result = rpc.prompt_and_collect(prompt, timeout=timeout)
                text_out = result.assistant_text
                tool_calls = result.tool_calls
                turn_count = result.turn_count
                compactions = result.compaction_events
                agent_ended = result.agent_ended
                # Why the run ended. Without it a crashed pi scores whatever
                # extract_final_answer() finds in a truncated transcript --
                # persisted, in seconds, indistinguishable from a genuine
                # wrong answer. getattr for older rpc_client.
                stop_reason = getattr(result, "stop_reason", "")
                notifications = rpc.notifications()
                stderr = rpc.stderr()
        except Exception as e:
            agent_error = f"{type(e).__name__}: {e}"

        elapsed = time.time() - t0
        model_answer = extract_final_answer(text_out)

        # Persist trajectory artifacts
        (task_dir / "transcript.txt").write_text(text_out)
        with (task_dir / "tool_calls.jsonl").open("w") as f:
            for tc in tool_calls:
                # Truncate result_text so we don't get megabytes of HTML
                row = dict(tc)
                rt = row.get("result_text") or ""
                row["result_text_len"] = len(rt)
                row["result_text"] = rt[:2000]
                f.write(json.dumps(row) + "\n")
        with (task_dir / "notifications.txt").open("w") as f:
            for n in notifications:
                f.write(f"[{n.get('notifyType', 'info')}] {n.get('message', '')}\n")
        if stderr:
            (task_dir / "stderr.log").write_text(stderr)

        result = {
            "task_id": task_id,
            "level": task.get("Level") or task.get("level"),
            "elapsed_s": round(elapsed, 2),
            "turn_count": turn_count,
            "n_tool_calls": len(tool_calls),
            "n_notifications": len(notifications),
            "compactions": compactions,
            "agent_ended": agent_ended,
            "stop_reason": stop_reason,
            "agent_error": agent_error,
            "model_answer": model_answer,
        }
        if score_against_gold:
            gold = task.get("Final answer") or task.get("final_answer") or ""
            ok, reason = score(model_answer, gold)
            result["gold"] = gold
            result["correct"] = ok
            result["score_reason"] = reason
        (task_dir / "result.json").write_text(json.dumps(result, indent=2))
        return result


def _load_transcript(out_dir: Path, task_id: str) -> str | None:
    """Read a task's saved assistant transcript if present (for reasoning_trace)."""
    p = out_dir / task_id / "transcript.txt"
    try:
        return p.read_text() if p.exists() else None
    except Exception:
        return None


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--split", choices=("validation", "test"), default="validation")
    ap.add_argument("--year", default="2023")
    ap.add_argument("--level", choices=("level1", "level2", "level3"), default=None)
    ap.add_argument("--task-ids", nargs="*", default=None,
                    help="Run only these task_ids (pilot mode)")
    ap.add_argument("--all", action="store_true",
                    help="Run the full split (ignored if --task-ids set)")
    ap.add_argument("--timeout", type=int, default=900,
                    help="Per-task timeout in seconds")
    ap.add_argument("--run-name", default=None,
                    help="Output dir name (default: <split>-<timestamp>)")
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap on number of tasks (0 = no cap)")
    ap.add_argument("--resume", action="store_true",
                    help="Skip task_ids that already have result.json under --run-name")
    args = ap.parse_args()

    print(f"loading dataset (split={args.split}, level={args.level or 'all'}, year={args.year})…",
          flush=True)
    records, dataset_root = _load_split(args.year, args.level, args.split)
    print(f"loaded {len(records)} tasks from {dataset_root}", flush=True)

    if args.task_ids:
        wanted = set(args.task_ids)
        records = [r for r in records if r["task_id"] in wanted]
        print(f"filtered to {len(records)} tasks by --task-ids", flush=True)
    elif not args.all:
        sys.exit("error: pass either --task-ids OR --all")

    if args.limit:
        records = records[:args.limit]

    run_name = args.run_name or f"{args.split}-{datetime.datetime.now().strftime('%Y-%m-%d__%H-%M-%S')}"
    out_dir = RUNS_ROOT / run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "model": args.model,
        "split": args.split,
        "year": args.year,
        "level": args.level,
        "n_tasks": len(records),
        "started_at": datetime.datetime.now().isoformat(),
        "task_ids": [r["task_id"] for r in records],
        "allowed_tools": ALLOWED_TOOLS,
    }
    # Don't overwrite a manifest from an earlier resume run — append a
    # restart entry instead so we have full provenance.
    manifest_path = out_dir / "manifest.json"
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text())
        except Exception:
            existing = {}
        restarts = existing.get("restarts", [])
        restarts.append({"at": manifest["started_at"], "n_tasks": manifest["n_tasks"]})
        existing["restarts"] = restarts
        manifest_path.write_text(json.dumps(existing, indent=2))
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2))

    score_against_gold = args.split == "validation"
    results: list[dict] = []

    # Resume: load any prior per-task result.json files and seed the in-memory
    # results list so the final summary covers them too.
    already_done: set[str] = set()
    if args.resume:
        for tdir in out_dir.iterdir():
            if not tdir.is_dir():
                continue
            rfile = tdir / "result.json"
            if not rfile.exists():
                continue
            try:
                prior = json.loads(rfile.read_text())
                already_done.add(prior["task_id"])
                results.append(prior)
            except Exception:
                pass
        if already_done:
            print(f"resume: {len(already_done)} task(s) already complete, will skip", flush=True)

    # submission.jsonl is rebuilt from per-task result.json each pass so resume
    # always converges on the canonical answer set.
    def _rewrite_submission():
        with (out_dir / "submission.jsonl").open("w") as f:
            for r in results:
                trace = (_load_transcript(out_dir, r["task_id"]) or "")[-2000:]
                f.write(json.dumps({
                    "task_id": r["task_id"],
                    "model_answer": r.get("model_answer", ""),
                    "reasoning_trace": trace,
                }) + "\n")

    _rewrite_submission()

    for i, task in enumerate(records, 1):
        tid = task["task_id"]
        if tid in already_done:
            continue
        print(f"\n[{i}/{len(records)}] {tid}  L{task.get('Level','?')} — running…",
              flush=True)
        r = _run_task(task, args.model, out_dir, dataset_root, args.timeout,
                      score_against_gold)
        results.append(r)
        # Persist results.json + submission.jsonl incrementally so a Ctrl-C
        # at any point leaves a usable, leaderboard-shaped artifact.
        (out_dir / "results.json").write_text(json.dumps(results, indent=2))
        _rewrite_submission()
        marker = "PASS" if r.get("correct") else ("FAIL" if score_against_gold else "DONE")
        print(f"    {marker}  ans={r['model_answer']!r}  in {r['elapsed_s']}s  ({r['turn_count']} turns, {r['n_tool_calls']} tool calls)")

    # Summary
    if score_against_gold:
        n_correct = sum(1 for r in results if r.get("correct"))
        n_total = len(results)
        pct = (n_correct / n_total * 100) if n_total else 0.0
        by_level: dict[str, list[bool]] = {}
        for r in results:
            by_level.setdefault(str(r.get("level")), []).append(bool(r.get("correct")))
        print(f"\n=== {n_correct}/{n_total} = {pct:.2f}% ===")
        for lvl, xs in sorted(by_level.items()):
            print(f"  L{lvl}: {sum(xs)}/{len(xs)}")
    print(f"\nrun: {out_dir}")


if __name__ == "__main__":
    main()
