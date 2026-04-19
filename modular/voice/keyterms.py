"""Voice keyterms: domain-specific vocabulary hints for STT accuracy.

Passed as Whisper's `initial_prompt` so that coding terminology
(grep, MCP, TypeScript, JSON, …) is recognised correctly instead of being
mistranscribed as phonetically similar common words.

Inspired by Claude Code's voiceKeyterms.ts, but expanded for a multi-provider
setting and adapted to pull context from the Python runtime environment.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# ── Global coding keyterms ────────────────────────────────────────────────
# Terms that speech engines consistently mishear during coding dictation.
# Exclude anything trivially recognised (e.g. "file", "code") — only add
# terms where phonetic ambiguity is high.

GLOBAL_KEYTERMS: list[str] = [
    # Tools and protocols
    "MCP",
    "grep",
    "regex",
    "regex pattern",
    "ripgrep",
    "localhost",
    "codebase",
    "webhook",
    "OAuth",
    "gRPC",
    "JSON",
    "YAML",
    "dotfiles",
    "symlink",
    "subprocess",
    "subagent",
    "worktree",
    # Languages / runtimes
    "TypeScript",
    "JavaScript",
    "Python",
    "Rust",
    "Golang",
    "Dockerfile",
    "bash",
    # Common coding words with phonetic twins
    "pytest",
    "linter",
    "formatter",
    "middleware",
    "endpoint",
    "namespace",
    "async",
    "await",
    "refactor",
    "deprecate",
    "serialize",
    "deserialize",
    "Pydantic",
    "FastAPI",
    "SQLAlchemy",
]

MAX_KEYTERMS = 50


# ── Helpers ───────────────────────────────────────────────────────────────

def split_identifier(name: str) -> list[str]:
    """Split camelCase / PascalCase / kebab-case / snake_case into words.

    Fragments ≤ 2 chars or > 20 chars are discarded.

    Examples:
        "little-coder" → ["nano", "claude", "code"]
        "MyWebhookHandler" → ["My", "Webhook", "Handler"]
    """
    # camelCase / PascalCase
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    parts = re.split(r"[-_./\s]+", spaced)
    return [p.strip() for p in parts if 3 <= len(p.strip()) <= 20]


def _git_branch() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        branch = result.stdout.strip()
        return branch if branch and branch != "HEAD" else None
    except Exception:
        return None


def _project_root() -> Path | None:
    """Find the git root or fall back to cwd."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=3,
        )
        root = result.stdout.strip()
        if root:
            return Path(root)
    except Exception:
        pass
    return Path.cwd()


def _recent_py_files(root: Path, limit: int = 20) -> list[Path]:
    """Return the most-recently modified Python/TS/JS files in the repo."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=5, cwd=str(root),
        )
        files = [
            root / f for f in result.stdout.splitlines()
            if f.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"))
        ]
        # Sort by mtime descending
        files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        return files[:limit]
    except Exception:
        return []


# ── Public API ────────────────────────────────────────────────────────────

def get_voice_keyterms(recent_files: list[str] | None = None) -> list[str]:
    """Build a list of keyterms for the STT engine.

    Combines:
      • Hardcoded global coding vocabulary
      • Project root directory name
      • Git branch words
      • Recent source file stem words

    Returns up to MAX_KEYTERMS unique terms.
    """
    terms: list[str] = list(GLOBAL_KEYTERMS)

    # Project name
    root = _project_root()
    if root and root.name:
        name = root.name
        if 2 < len(name) <= 50:
            terms.append(name)
        terms.extend(split_identifier(name))

    # Git branch words (e.g. "feat/voice-input" → ["feat", "voice", "input"])
    branch = _git_branch()
    if branch:
        terms.extend(split_identifier(branch))

    # Recent file stems
    files = [Path(f) for f in (recent_files or [])] + _recent_py_files(root or Path.cwd())
    for fpath in files:
        if len(terms) >= MAX_KEYTERMS:
            break
        stem = fpath.stem
        if stem:
            terms.extend(split_identifier(stem))

    # Deduplicate preserving order, trim to limit
    seen: set[str] = set()
    result: list[str] = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            result.append(t)
        if len(result) >= MAX_KEYTERMS:
            break

    return result
