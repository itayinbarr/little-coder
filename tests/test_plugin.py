"""Tests for the plugin package (plugin/)."""
from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from plugin.types import (
    PluginManifest, PluginEntry, PluginScope,
    parse_plugin_identifier, sanitize_plugin_name,
)
from plugin.recommend import (
    recommend_plugins, recommend_from_files, format_recommendations,
    PluginRecommendation,
)
import plugin.store as _store


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def tmp_plugin_paths(tmp_path, monkeypatch):
    """Redirect all plugin config paths to tmp_path."""
    user_cfg  = tmp_path / "user_plugins.json"
    user_dir  = tmp_path / "user_plugins"
    proj_cfg  = tmp_path / "proj_plugins.json"
    proj_dir  = tmp_path / "proj_plugins"

    monkeypatch.setattr(_store, "USER_PLUGIN_DIR", user_dir)
    monkeypatch.setattr(_store, "USER_PLUGIN_CFG", user_cfg)
    monkeypatch.setattr(_store, "_project_plugin_dir", lambda: proj_dir)
    monkeypatch.setattr(_store, "_project_plugin_cfg", lambda: proj_cfg)
    return tmp_path


@pytest.fixture()
def local_plugin(tmp_path):
    """Create a minimal local plugin directory."""
    d = tmp_path / "my_plugin"
    d.mkdir()
    manifest = {
        "name": "my-plugin",
        "version": "0.1.0",
        "description": "A test plugin",
        "author": "tester",
        "tags": ["test", "demo"],
        "tools": [],
        "skills": [],
    }
    (d / "plugin.json").write_text(json.dumps(manifest))
    return d


# ── types ─────────────────────────────────────────────────────────────────────

class TestPluginTypes:
    def test_parse_simple(self):
        name, src = parse_plugin_identifier("myplugin")
        assert name == "myplugin"
        assert src is None

    def test_parse_with_source(self):
        name, src = parse_plugin_identifier("myplugin@https://github.com/x/y")
        assert name == "myplugin"
        assert src == "https://github.com/x/y"

    def test_sanitize_name(self):
        assert sanitize_plugin_name("my-plugin.v2") == "my_plugin_v2"
        assert sanitize_plugin_name("ok_name") == "ok_name"

    def test_manifest_from_dict(self):
        m = PluginManifest.from_dict({
            "name": "test",
            "version": "1.2.3",
            "tags": ["a", "b"],
            "tools": ["tools"],
        })
        assert m.name == "test"
        assert m.version == "1.2.3"
        assert m.tags == ["a", "b"]
        assert m.tools == ["tools"]

    def test_manifest_defaults(self):
        m = PluginManifest.from_dict({"name": "x"})
        assert m.version == "0.1.0"
        assert m.tags == []
        assert m.tools == []

    def test_manifest_from_plugin_dir_json(self, tmp_path, local_plugin):
        m = PluginManifest.from_plugin_dir(local_plugin)
        assert m is not None
        assert m.name == "my-plugin"
        assert m.description == "A test plugin"

    def test_manifest_from_plugin_dir_md(self, tmp_path):
        d = tmp_path / "mdplugin"
        d.mkdir()
        md = "---\nname: md-plugin\nversion: 2.0\ndescription: from markdown\n---\n# Docs"
        (d / "PLUGIN.md").write_text(md)
        m = PluginManifest.from_plugin_dir(d)
        assert m is not None
        assert m.name == "md-plugin"
        assert m.version == "2.0"

    def test_manifest_missing(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        m = PluginManifest.from_plugin_dir(d)
        assert m is None

    def test_entry_to_dict_roundtrip(self, tmp_path):
        entry = PluginEntry(
            name="foo",
            scope=PluginScope.USER,
            source="https://x.com/foo",
            install_dir=tmp_path / "foo",
            enabled=True,
        )
        d = entry.to_dict()
        restored = PluginEntry.from_dict(d)
        assert restored.name == "foo"
        assert restored.scope == PluginScope.USER
        assert restored.enabled is True

    def test_entry_qualified_name(self, tmp_path):
        entry = PluginEntry("bar", PluginScope.PROJECT, "", tmp_path)
        assert entry.qualified_name == "bar@project"


# ── store ─────────────────────────────────────────────────────────────────────

class TestPluginStore:
    def test_list_empty(self):
        assert _store.list_plugins() == []

    def test_install_local(self, local_plugin):
        ok, msg = _store.install_plugin(
            f"my-plugin@{local_plugin}", scope=PluginScope.USER
        )
        assert ok, msg
        entries = _store.list_plugins()
        assert len(entries) == 1
        assert entries[0].name == "my_plugin"  # hyphens sanitized to underscores

    def test_install_creates_dir(self, local_plugin):
        _store.install_plugin(f"myplugin@{local_plugin}", scope=PluginScope.USER)
        entries = _store.list_plugins()
        assert entries[0].install_dir.exists()

    def test_install_no_source_error(self):
        ok, msg = _store.install_plugin("nonexistent", scope=PluginScope.USER)
        assert not ok
        assert "No source" in msg or "not found" in msg.lower()

    def test_install_duplicate(self, local_plugin):
        _store.install_plugin(f"myplugin@{local_plugin}", scope=PluginScope.USER)
        ok2, msg2 = _store.install_plugin(f"myplugin@{local_plugin}", scope=PluginScope.USER)
        assert not ok2
        assert "already installed" in msg2

    def test_install_force(self, local_plugin):
        _store.install_plugin(f"myplugin@{local_plugin}", scope=PluginScope.USER)
        ok2, _ = _store.install_plugin(f"myplugin@{local_plugin}", scope=PluginScope.USER, force=True)
        assert ok2

    def test_get_plugin(self, local_plugin):
        _store.install_plugin(f"myplugin@{local_plugin}", scope=PluginScope.USER)
        entry = _store.get_plugin("myplugin")
        assert entry is not None
        assert entry.name == "myplugin"

    def test_get_plugin_missing(self):
        assert _store.get_plugin("doesntexist") is None

    def test_uninstall(self, local_plugin):
        _store.install_plugin(f"myplugin@{local_plugin}", scope=PluginScope.USER)
        ok, _ = _store.uninstall_plugin("myplugin")
        assert ok
        assert _store.list_plugins() == []

    def test_uninstall_not_found(self):
        ok, msg = _store.uninstall_plugin("ghost")
        assert not ok

    def test_enable_disable(self, local_plugin):
        _store.install_plugin(f"myplugin@{local_plugin}", scope=PluginScope.USER)
        ok, _ = _store.disable_plugin("myplugin")
        assert ok
        assert not _store.get_plugin("myplugin").enabled
        ok2, _ = _store.enable_plugin("myplugin")
        assert ok2
        assert _store.get_plugin("myplugin").enabled

    def test_disable_all(self, local_plugin, tmp_path):
        plugin2 = tmp_path / "p2"
        plugin2.mkdir()
        (plugin2 / "plugin.json").write_text(json.dumps({"name": "p2"}))
        _store.install_plugin(f"myplugin@{local_plugin}", scope=PluginScope.USER)
        _store.install_plugin(f"p2@{plugin2}", scope=PluginScope.USER)
        ok, msg = _store.disable_all_plugins()
        assert ok
        for e in _store.list_plugins():
            assert not e.enabled

    def test_update_local_path_rejected(self, local_plugin):
        _store.install_plugin(f"myplugin@{local_plugin}", scope=PluginScope.USER)
        ok, msg = _store.update_plugin("myplugin")
        assert not ok
        assert "local path" in msg

    def test_update_not_found(self):
        ok, msg = _store.update_plugin("ghost")
        assert not ok

    def test_project_scope(self, local_plugin):
        _store.install_plugin(f"myplugin@{local_plugin}", scope=PluginScope.PROJECT)
        user_only = _store.list_plugins(PluginScope.USER)
        proj_only = _store.list_plugins(PluginScope.PROJECT)
        assert len(user_only) == 0
        assert len(proj_only) == 1


# ── recommend ─────────────────────────────────────────────────────────────────

class TestPluginRecommend:
    def test_empty_context(self):
        recs = recommend_plugins("")
        assert recs == []

    def test_git_context(self):
        recs = recommend_plugins("working with git repository diff blame")
        names = [r.name for r in recs]
        assert "git-tools" in names

    def test_python_lint_context(self):
        recs = recommend_plugins("run mypy and ruff on python code")
        names = [r.name for r in recs]
        assert "python-linter" in names

    def test_sql_context(self):
        recs = recommend_plugins("query sqlite database tables")
        names = [r.name for r in recs]
        assert "sql-tools" in names

    def test_top_n(self):
        recs = recommend_plugins("git python docker sql test aws", top_n=3)
        assert len(recs) <= 3

    def test_sorted_by_score(self):
        recs = recommend_plugins("docker container compose", top_n=10)
        scores = [r.score for r in recs]
        assert scores == sorted(scores, reverse=True)

    def test_recommend_from_files(self, tmp_path):
        (tmp_path / "main.py").touch()
        (tmp_path / "Dockerfile").touch()
        (tmp_path / "query.sql").touch()
        files = list(tmp_path.iterdir())
        recs = recommend_from_files(files, top_n=5)
        names = [r.name for r in recs]
        assert len(recs) >= 1

    def test_format_recommendations(self):
        recs = [PluginRecommendation(
            name="git-tools",
            description="Git helpers",
            source="https://example.com/git-tools",
            score=5.0,
            reasons=["tags match: git"],
        )]
        text = format_recommendations(recs)
        assert "git-tools" in text
        assert "Install:" in text

    def test_format_empty(self):
        text = format_recommendations([])
        assert "No plugin recommendations" in text


# AskUserQuestion test class removed in the cosmetic refinement pass —
# AskUserQuestion itself was removed from tools.py (see the rationale
# comment in tools.py where _ask_user_question used to live).
