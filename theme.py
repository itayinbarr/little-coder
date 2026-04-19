"""little-coder visual identity — single source of truth for colors and styles.

Positioning: small-LLM coding agent optimized for Qwen3.5-9B. The palette
is designed to read as "AI / neural" without being cliché, and to signal
little-coder's distinct identity versus Claude Code's cyan-first defaults.

All colors are 24-bit hex. Rich automatically falls back to the nearest
256-color on terminals without truecolor support.

Every Rich print call in little-coder that needs a color goes through one
of the named `lc.*` styles below. To re-theme the whole REPL, swap hex
values in COLORS and nothing else needs to change.
"""
from __future__ import annotations

try:
    from rich.theme import Theme
    from rich.style import Style
    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False
    Theme = None
    Style = None


# ── Palette ─────────────────────────────────────────────────────────────────

COLORS = {
    # Primary brand color. Banner title, tool arrows, active elements.
    # Electric violet reads as "AI / neural" and stays distinctive against
    # Claude Code's cyan-first look without veering into meme colors.
    "primary":  "#7C3AED",

    # Accent. Tool names, interactive highlights, links, clickable hints.
    # Neon cyan pops against dark backgrounds and pairs with violet for a
    # tight two-color brand.
    "accent":   "#00D9FF",

    # Muted. Dim metadata: timestamps, long paths, secondary context.
    # Slate gray recedes but stays readable on both dark and light terms.
    "muted":    "#6B7380",

    # Success. Passing tests, completed tool calls, green status zone.
    # Spring green is clearly "good" without being the tired default.
    "success":  "#4ADE80",

    # Warning. Yellow status zone (70–85%), Write-guard icon, soft alerts.
    # Amber is warmer than pure yellow and more readable than bright.
    "warning":  "#F59E0B",

    # Error. Red status zone (>85%), test failures, tool errors, refusals.
    # Rose is alarming but less aggressive than pure red.
    "error":    "#F43F5E",

    # Panel backgrounds (optional — most renderables stay transparent).
    "bg_soft":  "#1E1B2E",

    # Body foreground. Near-white for main text on dark terminals.
    "fg_body":  "#E4E4E7",
}


# ── Rich theme ──────────────────────────────────────────────────────────────
#
# Every `lc.*` style name maps onto a Rich Style. Call sites use the style
# name (e.g. console.print("hi", style="lc.accent")) rather than hex values
# or raw color names, so the whole REPL can be re-themed by editing only
# the COLORS dict above.

def _build_theme() -> "Theme | None":
    if not _RICH_AVAILABLE:
        return None
    return Theme({
        # Typography
        "lc.title":       Style(color=COLORS["primary"], bold=True),
        "lc.subtitle":    Style(color=COLORS["muted"], italic=True),
        "lc.body":        Style(color=COLORS["fg_body"]),
        "lc.muted":       Style(color=COLORS["muted"]),
        "lc.accent":      Style(color=COLORS["accent"]),

        # Semantic states
        "lc.success":     Style(color=COLORS["success"], bold=True),
        "lc.warning":     Style(color=COLORS["warning"]),
        "lc.error":       Style(color=COLORS["error"], bold=True),

        # Tool-call rendering (used by print_tool_start / print_tool_end)
        "lc.tool.name":   Style(color=COLORS["accent"], bold=True),
        "lc.tool.args":   Style(color=COLORS["muted"]),
        "lc.tool.arrow":  Style(color=COLORS["primary"]),
        "lc.tool.ok":     Style(color=COLORS["success"]),
        "lc.tool.fail":   Style(color=COLORS["error"], bold=True),

        # Status line zones (used by status_line.format_status_line)
        "lc.status.ok":   Style(color=COLORS["success"]),
        "lc.status.warn": Style(color=COLORS["warning"], bold=True),
        "lc.status.bad":  Style(color=COLORS["error"], bold=True),

        # Diff rendering (used by tool result formatter for Edit / Write-create)
        "lc.diff.add":    Style(color=COLORS["success"]),
        "lc.diff.del":    Style(color=COLORS["error"]),
        "lc.diff.meta":   Style(color=COLORS["muted"]),

        # Input prompt + permission prompts
        "lc.prompt":      Style(color=COLORS["primary"], bold=True),
        "lc.permission":  Style(color=COLORS["warning"], bold=True),
    })


THEME = _build_theme()


# ── Public API ─────────────────────────────────────────────────────────────

def get_theme() -> "Theme | None":
    """Return the Rich theme, or None if Rich isn't installed.

    Callers should pass this to Console(theme=get_theme()) at construction
    time. Styles resolve via `style="lc.accent"` etc. in print calls.
    """
    return THEME


def color(name: str) -> str:
    """Return a hex color from the palette by short name.

    For call sites that need a raw color string (ANSI escape codes, SVG
    output, etc.) rather than a Rich style name.

    Unknown names raise KeyError so typos don't silently produce white.
    """
    return COLORS[name]
