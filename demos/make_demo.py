#!/usr/bin/env python3
"""
Generate animated GIF demo of little-coder using PIL.
Simulates a realistic terminal session with tool calls.
"""
from PIL import Image, ImageDraw, ImageFont
import os, textwrap

# ── Catppuccin Mocha palette ─────────────────────────────────────────────
BG      = (30,  30,  46)   # base
SURFACE = (49,  50,  68)   # surface0
TEXT    = (205, 214, 244)  # text
SUBTEXT = (108, 112, 134)  # overlay0 (dim)
CYAN    = (137, 220, 235)  # sky
GREEN   = (166, 227, 161)  # green
YELLOW  = (249, 226, 175)  # yellow
RED     = (243, 139, 168)  # red
MAUVE   = (203, 166, 247)  # mauve (user prompt)
BLUE    = (137, 180, 250)  # blue
PEACH   = (250, 179, 135)  # peach

W, H = 960, 720
FONT_PATH  = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_BOLD  = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
FONT_SIZE  = 14
LINE_H     = 20
PAD_X      = 18
PAD_Y      = 16


def make_font(size=FONT_SIZE, bold=False):
    path = FONT_BOLD if bold else FONT_PATH
    try:
        return ImageFont.truetype(path, size)
    except:
        return ImageFont.load_default()


FONT      = make_font()
FONT_B    = make_font(bold=True)
FONT_SM   = make_font(FONT_SIZE - 1)


# ── Segment: (text, color, bold?) ────────────────────────────────────────
Seg = tuple   # (str, rgb_tuple, bool)


def seg(t, c=TEXT, b=False): return (t, c, b)
def segs(*args): return list(args)


def render_line(draw, y, segments, x_start=PAD_X):
    x = x_start
    for text, color, bold in segments:
        font = FONT_B if bold else FONT
        draw.text((x, y), text, font=font, fill=color)
        x += font.getlength(text)
    return y + LINE_H


def blank_frame():
    img = Image.new("RGB", (W, H), BG)
    return img


def draw_frame(lines_segments):
    """
    lines_segments: list of either
      - list[Seg]  → rendered as a line
      - None       → blank line
    Returns PIL Image.
    """
    img = blank_frame()
    d   = ImageDraw.Draw(img)
    y = PAD_Y
    for item in lines_segments:
        if item is None:
            y += LINE_H
        elif isinstance(item, list):
            y = render_line(d, y, item)
        else:
            y = render_line(d, y, [item])
    return img


# ── Pre-defined screen content blocks ───────────────────────────────────

BANNER = [
    [seg("╭─ little-coder ──────────────────────────────────────────╮", SUBTEXT)],
    [seg("│  ", SUBTEXT), seg("Model: ", SUBTEXT), seg("claude-opus-4-6", CYAN, True)],
    [seg("│  ", SUBTEXT), seg("Permissions: ", SUBTEXT), seg("auto", YELLOW)],
    [seg("│  Type /help for commands, Ctrl+C to cancel                  │", SUBTEXT)],
    [seg("╰────────────────────────────────────────────────────────────╯", SUBTEXT)],
    None,
]

def prompt_line(text="", cursor=False):
    cur = "█" if cursor else ""
    return [
        seg("[little-coder] ", SUBTEXT),
        seg("» ", CYAN, True),
        seg(text + cur, TEXT),
    ]

def claude_header():
    return [
        seg("╭─ Claude ", SUBTEXT),
        seg("●", GREEN),
        seg(" ─────────────────────────────────────────────", SUBTEXT),
    ]

def claude_sep():
    return [seg("╰──────────────────────────────────────────────────────────", SUBTEXT)]

def tool_line(icon, name, arg, color=CYAN):
    return [
        seg(f"  {icon}  ", SUBTEXT),
        seg(name, color),
        seg("(", SUBTEXT),
        seg(arg, TEXT),
        seg(")", SUBTEXT),
    ]

def tool_ok(msg):
    return [seg(f"  ✓ ", GREEN), seg(msg, SUBTEXT)]

def tool_err(msg):
    return [seg(f"  ✗ ", RED), seg(msg, SUBTEXT)]

def text_line(t, indent=2):
    return [seg(" " * indent + t, TEXT)]

def dim_line(t, indent=4):
    return [seg(" " * indent + t, SUBTEXT)]


# ── Scene builder ─────────────────────────────────────────────────────────

def build_scenes():
    """Return list of (frame_content, duration_ms)."""
    scenes = []
    def add(lines, ms=120):
        scenes.append((lines, ms))

    # ── Scene 0: Empty terminal with banner ──────────────────────────────
    add(BANNER + [prompt_line(cursor=True)], 800)

    # ── Scene 1: User types query 1 ──────────────────────────────────────
    msg1 = "List Python files in this project and show me their line counts"
    for i in range(0, len(msg1) + 1, 3):
        add(BANNER + [prompt_line(msg1[:i], cursor=(i < len(msg1)))], 60)
    add(BANNER + [prompt_line(msg1, cursor=False)], 400)

    # ── Scene 2: Claude header appears ──────────────────────────────────
    pre = BANNER + [prompt_line(msg1)]
    add(pre + [None, claude_header(), [seg("│ ", SUBTEXT)]], 300)

    # ── Scene 3: Tool call - Glob ────────────────────────────────────────
    base = pre + [None, claude_header()]
    add(base + [
        tool_line("⚙", "Glob", "**/*.py"),
    ], 500)
    add(base + [
        tool_line("⚙", "Glob", "**/*.py"),
        tool_ok("5 files matched"),
    ], 600)

    # ── Scene 4: Tool call - Bash (wc -l) ────────────────────────────────
    add(base + [
        tool_line("⚙", "Glob", "**/*.py"),
        tool_ok("5 files matched"),
        None,
        tool_line("⚙", "Bash", "wc -l *.py | sort -n"),
    ], 500)
    add(base + [
        tool_line("⚙", "Glob", "**/*.py"),
        tool_ok("5 files matched"),
        None,
        tool_line("⚙", "Bash", "wc -l *.py | sort -n"),
        tool_ok("→ 6 lines (120 chars)"),
    ], 700)

    # ── Scene 5: Claude streams response ────────────────────────────────
    response_lines = [
        "Here are the Python files in this project with their line counts:",
        "",
        "  76  config.py      — Configuration management and cost calculation",
        " 100  context.py     — System prompt builder, CLAUDE.md + git injection",
        " 173  agent.py       — Core agent loop with streaming API calls",
        " 359  tools.py       — 8 built-in tools (Read/Write/Edit/Bash/Glob/Grep/Web)",
        " 553  little_coder.py — REPL entry point, slash commands, rich rendering",
        "────────────────────────────────────────────────────",
        "1261  total",
        "",
        "The largest file is `little_coder.py` containing the interactive REPL,",
        "14 slash commands, permission handling, and markdown rendering.",
    ]
    tool_section = [
        tool_line("⚙", "Glob", "**/*.py"),
        tool_ok("5 files matched"),
        None,
        tool_line("⚙", "Bash", "wc -l *.py | sort -n"),
        tool_ok("→ 6 lines (120 chars)"),
        None,
        [seg("│ ", SUBTEXT)],
    ]
    streamed = []
    for i, rline in enumerate(response_lines):
        streamed.append(text_line(rline, 2))
        content = base + tool_section + streamed
        add(content, 80 if rline else 30)

    add(base + tool_section + [text_line(l, 2) for l in response_lines] + [claude_sep()], 1200)

    # ── Scene 6: New prompt appears ──────────────────────────────────────
    full1 = (pre + [None, claude_header()] +
             tool_section +
             [text_line(l, 2) for l in response_lines] +
             [claude_sep(), None])
    add(full1 + [prompt_line(cursor=True)], 800)

    # ── Scene 7: User types query 2 ──────────────────────────────────────
    msg2 = "Write a hello_world.py that prints 'Hello from little-coder!'"
    for i in range(0, len(msg2) + 1, 4):
        add(full1 + [prompt_line(msg2[:i], cursor=(i < len(msg2)))], 55)
    add(full1 + [prompt_line(msg2)], 400)

    # ── Scene 8: Write tool call ─────────────────────────────────────────
    base2 = full1 + [prompt_line(msg2), None, claude_header()]
    add(base2 + [
        tool_line("⚙", "Write", "/tmp/hello_world.py", MAUVE),
    ], 600)
    add(base2 + [
        tool_line("⚙", "Write", "/tmp/hello_world.py", MAUVE),
        tool_ok("Wrote 3 lines to /tmp/hello_world.py"),
        None,
        tool_line("⚙", "Bash", "python3 /tmp/hello_world.py"),
    ], 500)
    add(base2 + [
        tool_line("⚙", "Write", "/tmp/hello_world.py", MAUVE),
        tool_ok("Wrote 3 lines to /tmp/hello_world.py"),
        None,
        tool_line("⚙", "Bash", "python3 /tmp/hello_world.py"),
        tool_ok("→ Hello from little-coder!"),
    ], 800)

    # ── Scene 9: Final response ──────────────────────────────────────────
    resp2 = [
        "Done! Created `/tmp/hello_world.py` and ran it successfully.",
        "",
        "  print('Hello from little-coder!')",
        "",
        "Output: Hello from little-coder!",
    ]
    tool2 = [
        tool_line("⚙", "Write", "/tmp/hello_world.py", MAUVE),
        tool_ok("Wrote 3 lines to /tmp/hello_world.py"),
        None,
        tool_line("⚙", "Bash", "python3 /tmp/hello_world.py"),
        tool_ok("→ Hello from little-coder!"),
        None,
        [seg("│ ", SUBTEXT)],
    ]
    streamed2 = []
    for rline in resp2:
        streamed2.append(text_line(rline, 2))
        add(base2 + tool2 + streamed2, 90)

    add(base2 + tool2 + [text_line(l, 2) for l in resp2] + [claude_sep()], 1500)

    # ── Scene 10: Slash command demo ─────────────────────────────────────
    final_state = (full1 + [prompt_line(msg2), None, claude_header()] +
                   tool2 + [text_line(l, 2) for l in resp2] + [claude_sep(), None])
    add(final_state + [prompt_line(cursor=True)], 600)

    slash = "/cost"
    for i in range(len(slash) + 1):
        add(final_state + [prompt_line(slash[:i], cursor=(i < len(slash)))], 80)
    add(final_state + [prompt_line(slash)], 400)

    # cost output
    cost_lines = [
        [seg("Input tokens:  ", CYAN), seg("1,842", TEXT, True)],
        [seg("Output tokens: ", CYAN), seg("312", TEXT, True)],
        [seg("Est. cost:     ", CYAN), seg("$0.0318 USD", GREEN, True)],
    ]
    add(final_state + [prompt_line(slash), None] + cost_lines + [None, prompt_line(cursor=True)], 2000)

    return scenes


# ── Render ────────────────────────────────────────────────────────────────

def _build_explicit_palette():
    """
    Build a 256-entry palette from our exact theme colors.
    Returns flat list of 768 ints (R,G,B, R,G,B, ...) suitable for putpalette().
    """
    # All distinct colors used in the renderer
    theme = [
        BG, SURFACE, TEXT, SUBTEXT,
        CYAN, GREEN, YELLOW, RED, MAUVE, BLUE, PEACH,
        (255, 255, 255), (0, 0, 0),
        # Extra intermediate shades that PIL might snap to
        (50, 55, 80),   # surface variant
        (90, 95, 120),  # dim text variant
        (160, 166, 200),
    ]
    flat = []
    for c in theme:
        flat.extend(c)
    # Pad to 256 entries with black
    while len(flat) < 256 * 3:
        flat.extend((0, 0, 0))
    return flat


def render_gif(output_path="demo.gif"):
    print("Building scenes...")
    scenes = build_scenes()
    print(f"  {len(scenes)} scenes")

    palette_data = _build_explicit_palette()

    # Create a palette-mode reference image for quantize()
    pal_ref = Image.new("P", (1, 1))
    pal_ref.putpalette(palette_data)

    print("  Rendering frames...")
    rgb_frames = []
    durations  = []
    for i, (lines, ms) in enumerate(scenes):
        img = draw_frame(lines)
        rgb_frames.append(img)
        durations.append(ms)
        if i % 20 == 0:
            print(f"  {i}/{len(scenes)}...")

    # Quantize all frames to the same explicit palette (no dither → exact snap)
    print("  Quantizing to global palette...")
    p_frames = [f.quantize(palette=pal_ref, dither=0) for f in rgb_frames]

    print(f"Saving GIF → {output_path}  ({len(p_frames)} frames)...")
    p_frames[0].save(
        output_path,
        save_all=True,
        append_images=p_frames[1:],
        duration=durations,
        loop=0,
        optimize=False,
    )
    size_kb = os.path.getsize(output_path) // 1024
    print(f"Done! {size_kb} KB")


# ── Static screenshot ─────────────────────────────────────────────────────

def render_screenshot(output_path="screenshot.png"):
    """Single high-quality screenshot showing a complete session."""
    lines = (
        BANNER +
        [prompt_line("List Python files and their line counts")] +
        [None, claude_header()] +
        [
            tool_line("⚙", "Glob", "**/*.py"),
            tool_ok("5 files matched"),
            None,
            tool_line("⚙", "Bash", "wc -l *.py | sort -n"),
            tool_ok("→ 6 lines (120 chars)"),
            None,
            [seg("│ ", SUBTEXT)],
            text_line("Here are the Python files with their line counts:", 2),
            None,
            text_line("  76  config.py      — Configuration management", 2),
            text_line(" 100  context.py     — System prompt + git injection", 2),
            text_line(" 173  agent.py       — Core agent loop", 2),
            text_line(" 359  tools.py       — 8 built-in tools", 2),
            text_line(" 553  little_coder.py — REPL + slash commands", 2),
            text_line("────────────────────────────────", 2),
            text_line("1261  total", 2),
            None,
            text_line("The main entry point `little_coder.py` contains the REPL,", 2),
            text_line("14 slash commands, permission handling, and rich rendering.", 2),
            claude_sep(),
            None,
            prompt_line("/cost"),
            None,
            [seg("Input tokens:  ", CYAN), seg("1,842", TEXT, True)],
            [seg("Output tokens: ", CYAN), seg("312", TEXT, True)],
            [seg("Est. cost:     ", CYAN), seg("$0.0318 USD", GREEN, True)],
            None,
            prompt_line(cursor=True),
        ]
    )
    img = draw_frame(lines)

    # Add subtle rounded border effect
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W-1, H-1], outline=SURFACE, width=2)

    img.save(output_path, format="PNG", optimize=True)
    size_kb = os.path.getsize(output_path) // 1024
    print(f"Screenshot saved: {output_path}  ({size_kb} KB)")


if __name__ == "__main__":
    docs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")

    gif_path = os.path.join(docs_dir, "demo.gif")
    png_path = os.path.join(docs_dir, "screenshot.png")

    render_screenshot(png_path)
    render_gif(gif_path)
    print("\nFiles created:")
    print(f"  {png_path}")
    print(f"  {gif_path}")
