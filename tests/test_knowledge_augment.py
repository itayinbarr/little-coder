"""Tests for domain-knowledge augmentation system."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from local.knowledge_augment import (
    load_knowledge_entries,
    select_and_inject_knowledge,
    _score_entry,
    clear_cache,
)


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset the knowledge cache before each test."""
    clear_cache()
    yield
    clear_cache()


def test_loads_knowledge_files():
    """At least 3 knowledge entries load from disk."""
    entries = load_knowledge_entries()
    assert len(entries) >= 3, f"Expected >=3 entries, got {len(entries)}: {list(entries.keys())}"


def test_entries_have_prompts():
    """Every loaded entry has a non-empty body."""
    entries = load_knowledge_entries()
    for topic, skill in entries.items():
        assert skill.prompt, f"Entry '{topic}' has empty prompt"
        assert len(skill.prompt) > 20, f"Entry '{topic}' prompt too short"


def test_graph_traversal_detected():
    """'find shortest path in graph' should trigger graph traversal entry."""
    entries = load_knowledge_entries()
    scores = {topic: _score_entry("find shortest path in graph", topic) for topic in entries}
    best = max(scores, key=scores.get)
    assert "Graph Traversal" in best or "graph" in best.lower(), \
        f"Expected graph traversal, got '{best}' with scores: {scores}"


def test_dp_detected():
    """'count number of ways to climb stairs' should trigger DP entry."""
    entries = load_knowledge_entries()
    scores = {topic: _score_entry("count the number of ways to climb stairs", topic) for topic in entries}
    best = max(scores, key=scores.get)
    assert "Dynamic Programming" in best or "dp" in best.lower(), \
        f"Expected DP, got '{best}' with scores: {scores}"


def test_no_injection_irrelevant():
    """'edit the CSS file' should not trigger any knowledge injection."""
    config = {"knowledge_token_budget": 200, "context_limit": 8192}
    messages = [{"role": "user", "content": "edit the CSS file to change the background color"}]
    base = "You are a coding assistant."
    result, req_tools = select_and_inject_knowledge(base, messages, config)
    assert result == base, "Should not inject knowledge for irrelevant tasks"
    assert req_tools == []


def test_budget_respected():
    """With budget=100, at most 1 entry should be injected."""
    config = {"knowledge_token_budget": 100, "context_limit": 8192}
    messages = [{"role": "user", "content": (
        "implement DFS and BFS graph traversal with dynamic programming "
        "memoization and binary search on sorted array"
    )}]
    base = "You are a coding assistant."
    result, _ = select_and_inject_knowledge(base, messages, config)
    if result != base:
        # Count ### headings in the injected block
        injected = result[len(base):]
        headings = injected.count("### ")
        assert headings <= 1, f"Budget=100 should allow at most 1 entry, got {headings}"


def test_zero_budget():
    """Budget=0 should return base system unchanged."""
    config = {"knowledge_token_budget": 0, "context_limit": 8192}
    messages = [{"role": "user", "content": "implement DFS graph traversal"}]
    base = "You are a coding assistant."
    result, req_tools = select_and_inject_knowledge(base, messages, config)
    assert result == base
    assert req_tools == []


def test_subtask_skipped():
    """No injection when _is_subtask=True."""
    config = {"knowledge_token_budget": 200, "context_limit": 8192, "_is_subtask": True}
    messages = [{"role": "user", "content": "implement DFS graph traversal"}]
    base = "You are a coding assistant."
    result, _ = select_and_inject_knowledge(base, messages, config)
    assert result == base


def test_injection_format():
    """Injected block should have Algorithm Reference heading."""
    config = {"knowledge_token_budget": 300, "context_limit": 8192}
    messages = [{"role": "user", "content": "implement DFS and BFS graph traversal shortest path"}]
    base = "You are a coding assistant."
    result, _ = select_and_inject_knowledge(base, messages, config)
    if result != base:
        assert "## Algorithm Reference" in result
        assert "###" in result


def test_reference_docs_requires_read_tool():
    """Reference docs entry should report Read as required tool."""
    config = {"knowledge_token_budget": 300, "context_limit": 8192}
    messages = [{"role": "user", "content": "set up a docker compose file with redis and mysql for the adonis app"}]
    base = "You are a coding assistant."
    result, req_tools = select_and_inject_knowledge(base, messages, config)
    if result != base:
        assert "Read" in req_tools, f"Expected Read in required tools, got {req_tools}"
