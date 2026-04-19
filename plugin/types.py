"""Plugin system types: manifest, entry, scope."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class PluginScope(str, Enum):
    USER    = "user"     # ~/.little-coder/plugins/
    PROJECT = "project"  # .little-coder/plugins/ (cwd)


@dataclass
class PluginManifest:
    """Parsed from PLUGIN.md YAML frontmatter or plugin.json."""
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    tags: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)     # python modules exporting TOOL_DEFS
    skills: list[str] = field(default_factory=list)    # skill .md files
    commands: list[str] = field(default_factory=list)  # python modules exporting COMMAND_DEFS
    mcp_servers: dict[str, Any] = field(default_factory=dict)  # name → mcp server config
    dependencies: list[str] = field(default_factory=list)      # pip packages
    homepage: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "PluginManifest":
        return cls(
            name=data.get("name", "unknown"),
            version=str(data.get("version", "0.1.0")),
            description=data.get("description", ""),
            author=data.get("author", ""),
            tags=data.get("tags", []),
            tools=data.get("tools", []),
            skills=data.get("skills", []),
            commands=data.get("commands", []),
            mcp_servers=data.get("mcp_servers", {}),
            dependencies=data.get("dependencies", []),
            homepage=data.get("homepage", ""),
        )

    @classmethod
    def from_plugin_dir(cls, plugin_dir: Path) -> "PluginManifest | None":
        """Load manifest from a plugin directory (plugin.json or PLUGIN.md frontmatter)."""
        # Try plugin.json first
        json_file = plugin_dir / "plugin.json"
        if json_file.exists():
            import json
            try:
                return cls.from_dict(json.loads(json_file.read_text()))
            except Exception:
                pass

        # Try PLUGIN.md YAML frontmatter
        md_file = plugin_dir / "PLUGIN.md"
        if md_file.exists():
            return cls._from_md(md_file)

        return None

    @classmethod
    def _from_md(cls, md_file: Path) -> "PluginManifest | None":
        text = md_file.read_text()
        if not text.startswith("---"):
            return None
        end = text.find("---", 3)
        if end == -1:
            return None
        frontmatter = text[3:end].strip()
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(frontmatter)
        except ImportError:
            # Minimal YAML parser for simple key: value pairs
            data = {}
            for line in frontmatter.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    data[k.strip()] = v.strip()
        if isinstance(data, dict):
            return cls.from_dict(data)
        return None


@dataclass
class PluginEntry:
    """A plugin registered in the config store."""
    name: str
    scope: PluginScope
    source: str          # git URL, local path, or marketplace name@url
    install_dir: Path
    enabled: bool = True
    manifest: PluginManifest | None = None

    @property
    def qualified_name(self) -> str:
        return f"{self.name}@{self.scope.value}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "scope": self.scope.value,
            "source": self.source,
            "install_dir": str(self.install_dir),
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PluginEntry":
        return cls(
            name=data["name"],
            scope=PluginScope(data.get("scope", "user")),
            source=data.get("source", ""),
            install_dir=Path(data["install_dir"]),
            enabled=data.get("enabled", True),
        )


def parse_plugin_identifier(identifier: str) -> tuple[str, str | None]:
    """Parse 'name' or 'name@source'. Returns (name, source_or_None)."""
    if "@" in identifier:
        name, _, source = identifier.partition("@")
        return name.strip(), source.strip()
    return identifier.strip(), None


def sanitize_plugin_name(name: str) -> str:
    """Ensure plugin name is safe for use as directory name (alphanumeric + underscore)."""
    return re.sub(r"[^\w]", "_", name)
