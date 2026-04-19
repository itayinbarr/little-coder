"""Plugin recommendation engine: match installed + marketplace plugins to context."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import PluginManifest, PluginScope
from .store import list_plugins, USER_PLUGIN_DIR


# ── Marketplace ───────────────────────────────────────────────────────────────

BUILTIN_MARKETPLACE: list[dict] = [
    {
        "name": "git-tools",
        "description": "Extra git helpers: log graph, blame, bisect",
        "tags": ["git", "vcs", "version control", "diff", "blame"],
        "source": "https://github.com/little-coder-plugins/git-tools",
    },
    {
        "name": "python-linter",
        "description": "Run ruff/mypy/black on Python files",
        "tags": ["python", "lint", "format", "type check", "mypy", "ruff", "black"],
        "source": "https://github.com/little-coder-plugins/python-linter",
    },
    {
        "name": "docker-tools",
        "description": "Docker container management tools",
        "tags": ["docker", "container", "compose", "kubernetes", "k8s"],
        "source": "https://github.com/little-coder-plugins/docker-tools",
    },
    {
        "name": "web-scraper",
        "description": "Advanced web scraping with JavaScript rendering",
        "tags": ["web", "scrape", "html", "browser", "playwright", "selenium"],
        "source": "https://github.com/little-coder-plugins/web-scraper",
    },
    {
        "name": "sql-tools",
        "description": "Query and inspect SQL databases (SQLite, Postgres, MySQL)",
        "tags": ["sql", "database", "db", "sqlite", "postgres", "mysql", "query"],
        "source": "https://github.com/little-coder-plugins/sql-tools",
    },
    {
        "name": "test-runner",
        "description": "Run pytest/unittest and parse results",
        "tags": ["test", "pytest", "unittest", "coverage", "tdd"],
        "source": "https://github.com/little-coder-plugins/test-runner",
    },
    {
        "name": "diagram-tools",
        "description": "Generate Mermaid / PlantUML diagrams",
        "tags": ["diagram", "mermaid", "plantuml", "uml", "flowchart", "architecture"],
        "source": "https://github.com/little-coder-plugins/diagram-tools",
    },
    {
        "name": "aws-tools",
        "description": "AWS CLI wrapper tools (S3, EC2, Lambda, CloudWatch)",
        "tags": ["aws", "cloud", "s3", "ec2", "lambda", "cloudwatch", "iam"],
        "source": "https://github.com/little-coder-plugins/aws-tools",
    },
]


@dataclass
class PluginRecommendation:
    name: str
    description: str
    source: str
    score: float
    reasons: list[str]
    installed: bool = False
    enabled: bool = False


def _tokenize(text: str) -> set[str]:
    """Lower-case word tokens from text."""
    return set(re.findall(r"\b[a-z0-9_\-]+\b", text.lower()))


def _score_against_context(
    entry: dict,
    context_tokens: set[str],
) -> tuple[float, list[str]]:
    """Return (score, reasons) for a marketplace entry vs context tokens."""
    score = 0.0
    reasons: list[str] = []

    name_tokens = _tokenize(entry.get("name", ""))
    desc_tokens = _tokenize(entry.get("description", ""))
    tag_tokens: set[str] = set()
    for tag in entry.get("tags", []):
        tag_tokens.update(_tokenize(tag))

    # Tag match: highest weight
    tag_hits = tag_tokens & context_tokens
    if tag_hits:
        score += len(tag_hits) * 3.0
        reasons.append(f"tags match: {', '.join(sorted(tag_hits))}")

    # Name match
    name_hits = name_tokens & context_tokens
    if name_hits:
        score += len(name_hits) * 2.0
        reasons.append(f"name match: {', '.join(sorted(name_hits))}")

    # Description match
    desc_hits = desc_tokens & context_tokens - {"the", "a", "an", "and", "or", "of", "to", "in", "for", "with"}
    if desc_hits:
        score += len(desc_hits) * 0.5

    return score, reasons


def recommend_plugins(
    context: str,
    top_n: int = 5,
    include_installed: bool = False,
) -> list[PluginRecommendation]:
    """
    Given a natural-language context string (e.g. current task description or
    user message), return up to top_n plugin recommendations sorted by relevance.

    Args:
        context: Free-text description of the current task / need.
        top_n: Maximum number of recommendations.
        include_installed: If True, include already-installed plugins in results.
    """
    context_tokens = _tokenize(context)
    if not context_tokens:
        return []

    # Build installed set
    installed_entries = list_plugins()
    installed_names = {e.name for e in installed_entries}
    installed_enabled = {e.name for e in installed_entries if e.enabled}

    # Also add tags from installed plugins to context (cross-pollination)
    for entry in installed_entries:
        if entry.manifest:
            for tag in entry.manifest.tags:
                context_tokens.update(_tokenize(tag))

    results: list[PluginRecommendation] = []

    for mp_entry in BUILTIN_MARKETPLACE:
        name = mp_entry["name"]
        is_installed = name in installed_names
        is_enabled = name in installed_enabled

        if is_installed and not include_installed:
            continue

        score, reasons = _score_against_context(mp_entry, context_tokens)
        if score > 0:
            results.append(PluginRecommendation(
                name=name,
                description=mp_entry.get("description", ""),
                source=mp_entry.get("source", ""),
                score=score,
                reasons=reasons,
                installed=is_installed,
                enabled=is_enabled,
            ))

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_n]


def recommend_from_files(
    paths: list[Path],
    top_n: int = 5,
) -> list[PluginRecommendation]:
    """Recommend plugins based on the types of files in the current project."""
    context_parts: list[str] = []
    ext_map = {
        ".py": "python",
        ".ts": "typescript javascript",
        ".tsx": "typescript react javascript",
        ".js": "javascript",
        ".rs": "rust",
        ".go": "golang",
        ".java": "java",
        ".sql": "sql database",
        ".dockerfile": "docker container",
        ".yaml": "yaml config",
        ".yml": "yaml config docker",
        ".tf": "terraform aws cloud",
        ".md": "markdown docs",
    }
    for p in paths:
        label = ext_map.get(p.suffix.lower(), "")
        if label:
            context_parts.append(label)

    return recommend_plugins(" ".join(context_parts), top_n=top_n)


def format_recommendations(recs: list[PluginRecommendation]) -> str:
    if not recs:
        return "No plugin recommendations for the current context."
    lines = ["Plugin recommendations:"]
    for i, rec in enumerate(recs, 1):
        status = " [installed]" if rec.installed else ""
        lines.append(f"  {i}. {rec.name}{status} — {rec.description}")
        if rec.reasons:
            lines.append(f"     Reason: {'; '.join(rec.reasons)}")
        lines.append(f"     Install: /plugin install {rec.name}@{rec.source}")
    return "\n".join(lines)
