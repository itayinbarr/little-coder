"""Plugin system for little-coder."""
from .types import PluginManifest, PluginEntry, PluginScope, parse_plugin_identifier
from .store import (
    install_plugin, uninstall_plugin,
    enable_plugin, disable_plugin, disable_all_plugins,
    update_plugin, list_plugins, get_plugin,
)
from .loader import (
    load_all_plugins, load_plugin_tools, load_plugin_skills,
    load_plugin_mcp_configs, register_plugin_tools,
)
from .recommend import recommend_plugins, recommend_from_files, format_recommendations

__all__ = [
    "PluginManifest", "PluginEntry", "PluginScope", "parse_plugin_identifier",
    "install_plugin", "uninstall_plugin",
    "enable_plugin", "disable_plugin", "disable_all_plugins",
    "update_plugin", "list_plugins", "get_plugin",
    "load_all_plugins", "load_plugin_tools", "load_plugin_skills",
    "load_plugin_mcp_configs", "register_plugin_tools",
    "recommend_plugins", "recommend_from_files", "format_recommendations",
]
