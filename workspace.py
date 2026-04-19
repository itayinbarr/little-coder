"""Workspace introspection utilities.

General-purpose helpers for looking at a directory and answering two
questions the agent often needs but has no direct hook for:

    1. What programming language is this project?
    2. What documentation / specification files are in it?

These are kept language-agnostic and side-effect-free so they can be
called from the benchmark harness, the skill system, or any future
workspace-awareness feature without pulling in model state or config.

The detection rules are deliberately build-system-based, not
extension-based — a directory containing only a single `.py` file is
not a "python project" in the sense the agent cares about, but a
directory with `pyproject.toml` or `*_test.py` is.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


# Fingerprint checks in priority order. Java is first because its layout
# (gradlew + build.gradle + src/main/java) is the most distinctive and
# could otherwise collide with a sub-project's CMakeLists or package.json.
_LANGUAGE_FINGERPRINTS: list[tuple[str, callable]] = [
    ("java",       lambda d: (d / "build.gradle").exists() and (d / "gradlew").exists()),
    ("rust",       lambda d: (d / "Cargo.toml").exists()),
    ("go",         lambda d: (d / "go.mod").exists()),
    ("cpp",        lambda d: (d / "CMakeLists.txt").exists()),
    ("javascript", lambda d: (d / "package.json").exists()
                             and any(d.glob("*.spec.js"))),
    ("python",     lambda d: (d / "pyproject.toml").exists()
                             or any(d.glob("*_test.py"))
                             or any(d.glob("test_*.py"))),
]


def detect_language(directory: Path | str) -> Optional[str]:
    """Return the language name for a directory, or None if unknown.

    Recognizes python / go / rust / cpp / javascript / java by the
    build-system files or test-file conventions they ship with. Returns
    None for non-project directories (empty, or containing unrelated
    files) so callers can treat it as "no strong signal" rather than
    a failure.
    """
    d = Path(directory)
    if not d.is_dir():
        return None
    for name, matches in _LANGUAGE_FINGERPRINTS:
        try:
            if matches(d):
                return name
        except Exception:
            continue
    return None


# Documentation files that commonly describe what a project or task is
# supposed to do. Order matters — more specific / more useful first.
# The agent should Read the first one that exists, not all of them.
_DOC_CANDIDATES: list[str] = [
    ".docs/instructions.md",        # exercism-style problem specs
    ".docs/instructions.append.md", # exercism extra notes
    "AGENTS.md",                    # agent-specific repo instructions
    "CLAUDE.md",                    # agent-specific repo instructions
    "SPEC.md",
    "SPECIFICATION.md",
    "README.md",
    "docs/README.md",
]


def find_workspace_docs(directory: Path | str) -> list[Path]:
    """Return paths of documentation files present in a directory.

    Results are ordered by the priority in _DOC_CANDIDATES, so callers
    can treat the first element as "the most relevant doc to read first."
    Returns an empty list if nothing matched.
    """
    d = Path(directory)
    if not d.is_dir():
        return []
    found: list[Path] = []
    for rel in _DOC_CANDIDATES:
        p = d / rel
        if p.is_file():
            found.append(p)
    return found


def read_exercise_spec(directory: Path | str) -> str:
    """Return concatenated spec docs from a directory's .docs/ folder.

    Convenience wrapper for the exercism-style layout where problem
    specifications live at `.docs/instructions.md` (+ optional
    `.docs/instructions.append.md`). Returns an empty string if no
    spec docs are present — the caller can branch on truthiness.
    """
    d = Path(directory)
    docs_dir = d / ".docs"
    if not docs_dir.is_dir():
        return ""
    parts: list[str] = []
    for name in ("instructions.md", "instructions.append.md"):
        p = docs_dir / name
        if p.is_file():
            parts.append(p.read_text())
    return "\n\n".join(parts)
