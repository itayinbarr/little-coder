"""Tests for the memory package (memory/)."""
import pytest
from pathlib import Path

import memory.store as _store
from memory.store import (
    MemoryEntry,
    save_memory,
    load_index,
    load_entries,
    delete_memory,
    search_memory,
    _slugify,
    parse_frontmatter,
    get_index_content,
)
from memory.context import get_memory_context, truncate_index_content
from memory.scan import (
    scan_memory_dir,
    format_memory_manifest,
    memory_age_days,
    memory_age_str,
    memory_freshness_text,
    MemoryHeader,
)
from memory.types import MEMORY_TYPES


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def redirect_memory_dirs(tmp_path, monkeypatch):
    """Redirect user and project memory dirs to tmp_path for all tests."""
    user_mem = tmp_path / "user_memory"
    user_mem.mkdir()
    proj_mem = tmp_path / "project_memory"
    proj_mem.mkdir()

    monkeypatch.setattr(_store, "USER_MEMORY_DIR", user_mem)

    # Patch get_project_memory_dir to return our tmp project dir
    monkeypatch.setattr(_store, "get_project_memory_dir", lambda: proj_mem)


def _make_entry(name="test note", description="a test", type_="user",
                content="hello world", scope="user"):
    return MemoryEntry(
        name=name, description=description, type=type_,
        content=content, created="2026-04-02", scope=scope,
    )


# ── Save and Load ─────────────────────────────────────────────────────────

class TestSaveAndLoad:
    def test_roundtrip(self):
        entry = _make_entry()
        save_memory(entry, scope="user")
        loaded = load_entries("user")
        assert len(loaded) == 1
        assert loaded[0].name == "test note"
        assert loaded[0].description == "a test"
        assert loaded[0].type == "user"
        assert loaded[0].content == "hello world"

    def test_creates_file_on_disk(self):
        entry = _make_entry()
        save_memory(entry, scope="user")
        assert Path(entry.file_path).exists()
        text = Path(entry.file_path).read_text()
        assert "hello world" in text

    def test_update_existing(self):
        """Save same name twice → only 1 entry with updated content."""
        save_memory(_make_entry(content="version 1"), scope="user")
        save_memory(_make_entry(content="version 2"), scope="user")
        loaded = load_entries("user")
        assert len(loaded) == 1
        assert loaded[0].content == "version 2"

    def test_project_scope_stored_separately(self):
        save_memory(_make_entry(name="user note"), scope="user")
        save_memory(_make_entry(name="proj note"), scope="project")
        user_entries = load_entries("user")
        proj_entries = load_entries("project")
        assert len(user_entries) == 1
        assert len(proj_entries) == 1
        assert user_entries[0].name == "user note"
        assert proj_entries[0].name == "proj note"

    def test_load_index_all_combines_scopes(self):
        save_memory(_make_entry(name="user note"), scope="user")
        save_memory(_make_entry(name="proj note"), scope="project")
        all_entries = load_index("all")
        names = {e.name for e in all_entries}
        assert "user note" in names
        assert "proj note" in names


# ── Delete ────────────────────────────────────────────────────────────────

class TestDelete:
    def test_delete_removes_file_and_index(self):
        entry = _make_entry()
        save_memory(entry, scope="user")
        delete_memory("test note", scope="user")
        assert load_entries("user") == []
        assert not Path(entry.file_path).exists()

    def test_delete_nonexistent_no_error(self):
        delete_memory("nonexistent", scope="user")

    def test_delete_from_project_scope(self):
        save_memory(_make_entry(name="proj note"), scope="project")
        delete_memory("proj note", scope="project")
        assert load_entries("project") == []


# ── Search ────────────────────────────────────────────────────────────────

class TestSearch:
    def test_search_by_keyword(self):
        save_memory(_make_entry(name="python tips", content="use list comprehension"), scope="user")
        save_memory(_make_entry(name="rust tips", content="use iterators"), scope="user")
        results = search_memory("python")
        assert len(results) == 1
        assert results[0].name == "python tips"

    def test_search_case_insensitive(self):
        save_memory(_make_entry(name="Important Note", content="something"), scope="user")
        results = search_memory("important")
        assert len(results) == 1

    def test_search_in_content(self):
        save_memory(_make_entry(name="misc", content="the quick brown fox"), scope="user")
        results = search_memory("brown fox")
        assert len(results) == 1

    def test_search_across_scopes(self):
        save_memory(_make_entry(name="user note", content="alpha"), scope="user")
        save_memory(_make_entry(name="proj note", content="alpha"), scope="project")
        results = search_memory("alpha", scope="all")
        assert len(results) == 2


# ── Memory context ────────────────────────────────────────────────────────

class TestGetMemoryContext:
    def test_returns_index_text(self):
        save_memory(_make_entry(name="my note", description="desc here"), scope="user")
        ctx = get_memory_context()
        assert "my note" in ctx
        assert "desc here" in ctx

    def test_empty_when_no_memories(self):
        ctx = get_memory_context()
        assert ctx == ""

    def test_project_memories_labelled(self):
        save_memory(_make_entry(name="proj note", description="project context"), scope="project")
        ctx = get_memory_context()
        assert "Project memories" in ctx
        assert "proj note" in ctx


# ── Truncation ────────────────────────────────────────────────────────────

class TestTruncation:
    def test_no_truncation_within_limits(self):
        text = "- line\n" * 10
        result = truncate_index_content(text)
        assert "WARNING" not in result

    def test_line_truncation(self):
        text = "\n".join(f"- line {i}" for i in range(300))
        result = truncate_index_content(text)
        assert "WARNING" in result
        assert "lines" in result

    def test_byte_truncation(self):
        # 25001 bytes of content
        text = "x" * 25001
        result = truncate_index_content(text)
        assert "WARNING" in result


# ── Slugify ───────────────────────────────────────────────────────────────

class TestSlugify:
    def test_basic(self):
        assert _slugify("Hello World") == "hello_world"

    def test_special_chars(self):
        assert _slugify("foo@bar!baz") == "foobarbaz"

    def test_max_length(self):
        assert len(_slugify("a" * 100)) == 60


# ── parse_frontmatter ─────────────────────────────────────────────────────

class TestParseFrontmatter:
    def test_parse(self):
        text = "---\nname: foo\ntype: user\n---\nbody text"
        meta, body = parse_frontmatter(text)
        assert meta["name"] == "foo"
        assert meta["type"] == "user"
        assert body == "body text"

    def test_no_frontmatter(self):
        meta, body = parse_frontmatter("just plain text")
        assert meta == {}
        assert body == "just plain text"


# ── scan / age / freshness ────────────────────────────────────────────────

class TestScanAndAge:
    def test_scan_memory_dir(self):
        save_memory(_make_entry(name="note a"), scope="user")
        save_memory(_make_entry(name="note b"), scope="user")
        user_dir = _store.USER_MEMORY_DIR
        headers = scan_memory_dir(user_dir, "user")
        assert len(headers) == 2
        assert all(isinstance(h, MemoryHeader) for h in headers)

    def test_format_manifest(self):
        import time
        headers = [
            MemoryHeader(
                filename="foo.md",
                file_path="/tmp/foo.md",
                mtime_s=time.time(),
                description="test desc",
                type="user",
                scope="user",
            )
        ]
        manifest = format_memory_manifest(headers)
        assert "foo.md" in manifest
        assert "test desc" in manifest
        assert "today" in manifest

    def test_memory_age_days_today(self):
        import time
        assert memory_age_days(time.time()) == 0

    def test_memory_age_days_old(self):
        import time
        old = time.time() - 5 * 86400  # 5 days ago
        assert memory_age_days(old) == 5

    def test_memory_age_str(self):
        import time
        assert memory_age_str(time.time()) == "today"
        assert memory_age_str(time.time() - 86400) == "yesterday"
        assert memory_age_str(time.time() - 3 * 86400) == "3 days ago"

    def test_freshness_text_fresh(self):
        import time
        assert memory_freshness_text(time.time()) == ""

    def test_freshness_text_stale(self):
        import time
        old = time.time() - 10 * 86400
        text = memory_freshness_text(old)
        assert "10 days old" in text
        assert "stale" in text.lower() or "outdated" in text.lower()


# ── Memory types ──────────────────────────────────────────────────────────

class TestMemoryTypes:
    def test_types_list(self):
        assert set(MEMORY_TYPES) == {"user", "feedback", "project", "reference"}
