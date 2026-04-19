#!/usr/bin/env python3
"""
Generate animated GIF demo of little-coder SSJ Developer Mode.
Shows: /ssj menu → Brainstorm → TODO viewer → Worker → Exit
"""
from PIL import Image, ImageDraw, ImageFont
import os

# ── Catppuccin Mocha palette ─────────────────────────────────────────────
BG      = (30,  30,  46)
SURFACE = (49,  50,  68)
TEXT    = (205, 214, 244)
SUBTEXT = (108, 112, 134)
CYAN    = (137, 220, 235)
GREEN   = (166, 227, 161)
YELLOW  = (249, 226, 175)
RED     = (243, 139, 168)
MAUVE   = (203, 166, 247)
BLUE    = (137, 180, 250)
PEACH   = (250, 179, 135)
ORANGE  = (254, 100,  11)

W, H = 960, 720
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
FONT_SIZE = 14
LINE_H    = 20
PAD_X     = 18
PAD_Y     = 16


def make_font(size=FONT_SIZE, bold=False):
    path = FONT_BOLD if bold else FONT_PATH
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


FONT   = make_font()
FONT_B = make_font(bold=True)


def seg(t, c=TEXT, b=False):
    return (t, c, b)


def render_line(draw, y, segments, x_start=PAD_X):
    x = x_start
    for text, color, bold in segments:
        font = FONT_B if bold else FONT
        draw.text((x, y), text, font=font, fill=color)
        x += font.getlength(text)
    return y + LINE_H


def draw_frame(lines_segments):
    img = Image.new("RGB", (W, H), BG)
    d   = ImageDraw.Draw(img)
    y   = PAD_Y
    for item in lines_segments:
        if item is None:
            y += LINE_H
        elif isinstance(item, list):
            y = render_line(d, y, item)
        else:
            y = render_line(d, y, [item])
    return img


# ── Reusable blocks ──────────────────────────────────────────────────────

BANNER = [
    [seg("╭─ little-coder ──────────────────────────────────────────╮", SUBTEXT)],
    [seg("│  ", SUBTEXT), seg("Model: ", SUBTEXT), seg("claude-opus-4-6", CYAN, True)],
    [seg("│  ", SUBTEXT), seg("Permissions: ", SUBTEXT), seg("auto", YELLOW, True)],
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

def ssj_prompt(text="", cursor=False):
    cur = "█" if cursor else ""
    return [
        seg("  ⚡ SSJ » ", YELLOW, True),
        seg(text + cur, TEXT),
    ]

def claude_header():
    return [seg("╭─ Claude ", SUBTEXT), seg("●", GREEN), seg(" ─────────────────────────────────────────────", SUBTEXT)]

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
    return [seg("  ✓ ", GREEN), seg(msg, SUBTEXT)]

def text_line(t, indent=2):
    return [seg(" " * indent + t, TEXT)]

def dim_line(t, indent=4):
    return [seg(" " * indent + t, SUBTEXT)]

def ok_line(t):
    return [seg("  ✓ ", GREEN, True), seg(t, TEXT)]

def info_line(t):
    return [seg("  ℹ ", CYAN), seg(t, SUBTEXT)]

def err_line(t):
    return [seg("  ✗ ", RED), seg(t, SUBTEXT)]


# ── SSJ Menu ─────────────────────────────────────────────────────────────

SSJ_MENU = [
    None,
    [seg("╭─ SSJ Developer Mode ", SUBTEXT), seg("⚡", YELLOW, True), seg(" ─────────────────────────", SUBTEXT)],
    [seg("│", SUBTEXT)],
    [seg("│  ", SUBTEXT), seg(" 1.", TEXT, True), seg("  💡  Brainstorm ", TEXT), seg("— Multi-persona AI debate", SUBTEXT)],
    [seg("│  ", SUBTEXT), seg(" 2.", TEXT, True), seg("  📋  Show TODO  ", TEXT), seg("— View todo_list.txt", SUBTEXT)],
    [seg("│  ", SUBTEXT), seg(" 3.", TEXT, True), seg("  👷  Worker     ", TEXT), seg("— Auto-implement pending tasks", SUBTEXT)],
    [seg("│  ", SUBTEXT), seg(" 4.", TEXT, True), seg("  🧠  Debate     ", TEXT), seg("— Expert debate on a file", SUBTEXT)],
    [seg("│  ", SUBTEXT), seg(" 5.", TEXT, True), seg("  ✨  Propose    ", TEXT), seg("— AI improvement for a file", SUBTEXT)],
    [seg("│  ", SUBTEXT), seg(" 6.", TEXT, True), seg("  🔎  Review     ", TEXT), seg("— Quick file analysis", SUBTEXT)],
    [seg("│  ", SUBTEXT), seg(" 7.", TEXT, True), seg("  📘  Readme     ", TEXT), seg("— Auto-generate README.md", SUBTEXT)],
    [seg("│  ", SUBTEXT), seg(" 8.", TEXT, True), seg("  💬  Commit     ", TEXT), seg("— AI-suggested commit message", SUBTEXT)],
    [seg("│  ", SUBTEXT), seg(" 9.", TEXT, True), seg("  🧪  Scan       ", TEXT), seg("— Analyze git diff", SUBTEXT)],
    [seg("│  ", SUBTEXT), seg("10.", TEXT, True), seg("  📝  Promote    ", TEXT), seg("— Idea to tasks", SUBTEXT)],
    [seg("│  ", SUBTEXT), seg(" 0.", TEXT, True), seg("  🚪  Exit SSJ Mode", SUBTEXT)],
    [seg("│", SUBTEXT)],
    [seg("╰──────────────────────────────────────────────", SUBTEXT)],
]

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
THINK_PHRASES  = [
    "agents thinking",
    "agents thinking.",
    "agents thinking..",
    "agents thinking...",
]


def build_scenes():
    scenes = []

    def add(lines, ms=120):
        scenes.append((lines, ms))

    def type_into(base, prefix_lines, text, ms_per_chunk=55, chunk=3):
        """Animate typing `text` at the end of base+prefix_lines."""
        for i in range(0, len(text) + 1, chunk):
            add(base + prefix_lines(text[:i], cursor=(i < len(text))), ms_per_chunk)
        add(base + prefix_lines(text, cursor=False), 400)

    # ── 0. Banner ────────────────────────────────────────────────────────
    add(BANNER + [prompt_line(cursor=True)], 900)

    # ── 1. Type /ssj ─────────────────────────────────────────────────────
    cmd = "/ssj"
    for i in range(len(cmd) + 1):
        add(BANNER + [prompt_line(cmd[:i], cursor=(i < len(cmd)))], 80)
    add(BANNER + [prompt_line(cmd, cursor=False)], 350)

    # ── 2. SSJ menu appears ───────────────────────────────────────────────
    add(BANNER + [prompt_line(cmd)] + SSJ_MENU + [None, ssj_prompt(cursor=True)], 1400)

    # ── 3. Type "1" → Brainstorm ──────────────────────────────────────────
    base_menu = BANNER + [prompt_line(cmd)] + SSJ_MENU + [None]
    add(base_menu + [ssj_prompt("1", cursor=False)], 350)

    # Topic prompt
    topic_prompt = [
        [seg("  Topic (Enter for general): ", CYAN), seg("█", TEXT)],
    ]
    add(base_menu + [ssj_prompt("1")] + topic_prompt, 500)

    topic = "little-coder SSJ features"
    for i in range(0, len(topic) + 1, 3):
        add(base_menu + [ssj_prompt("1")] + [
            [seg("  Topic (Enter for general): ", CYAN), seg(topic[:i] + ("█" if i < len(topic) else ""), TEXT)],
        ], 60)
    add(base_menu + [ssj_prompt("1")] + [
        [seg("  Topic (Enter for general): ", CYAN), seg(topic, TEXT)],
    ], 400)

    # ── 4. Brainstorm spinner ─────────────────────────────────────────────
    add(base_menu + [ssj_prompt("1")] + [
        None,
        [seg("  ── Brainstorm: ", SUBTEXT), seg("little-coder SSJ features", CYAN), seg(" ──", SUBTEXT)],
        None,
        ok_line("Generating 4 topic-appropriate expert personas..."),
        None,
    ], 700)

    personas = [
        ("A", "Alex Rivera",   "UX Design Lead"),
        ("B", "Sam Chen",      "Backend Engineer"),
        ("C", "Taylor Morgan", "DevOps / Infra"),
        ("D", "Jordan Lee",    "Product Manager"),
    ]
    persona_lines = []
    for letter, name, role in personas:
        persona_lines.append(
            [seg(f"    [{letter}] ", CYAN, True), seg(f"{name}", TEXT, True), seg(f"  ({role})", SUBTEXT)]
        )

    spinner_base = base_menu + [ssj_prompt("1"), None,
        [seg("  ── Brainstorm: ", SUBTEXT), seg("little-coder SSJ features", CYAN), seg(" ──", SUBTEXT)],
        None,
        ok_line("Generating 4 topic-appropriate expert personas..."),
        None,
    ] + persona_lines + [None]

    # Spinning debate rounds
    debate_rounds = [
        ("A", "Alex Rivera",   "The SSJ menu drastically reduces cognitive overhead — no need to remember command names"),
        ("B", "Sam Chen",      "Worker auto-implementation is huge. One command to turn a TODO list into working code"),
        ("C", "Taylor Morgan", "Force-quit (3x Ctrl+C) is a must-have. Blocking I/O during brainstorm used to trap users"),
        ("D", "Jordan Lee",    "Brainstorm → TODO pipeline is the killer feature. Ideas become tasks automatically"),
        ("A", "Alex Rivera",   "Telegram integration means you can trigger the agent from your phone while on the go"),
        ("B", "Sam Chen",      "The /ssj passthrough lets you use any slash command without leaving the power menu"),
    ]

    debate_shown = []
    for idx, (letter, name, thought) in enumerate(debate_rounds):
        # Show spinner while "thinking"
        for si in range(4):
            spin = SPINNER_FRAMES[(idx * 4 + si) % len(SPINNER_FRAMES)]
            phrase = THINK_PHRASES[si % len(THINK_PHRASES)]
            add(spinner_base + debate_shown + [
                [seg(f"  {spin} ", CYAN), seg(f"[{letter}] {name}: ", YELLOW), seg(phrase, SUBTEXT)],
            ], 180)

        # Reveal the thought
        words = thought.split()
        thought_segs = [seg(f"  [{letter}] ", CYAN, True), seg(f"{name}: ", YELLOW, True)]
        shown_words = []
        for wi, w in enumerate(words):
            shown_words.append(w)
            add(spinner_base + debate_shown + [
                thought_segs + [seg(" ".join(shown_words), TEXT)],
            ], 40 if wi < len(words) - 1 else 100)

        debate_shown.append(
            [seg(f"  [{letter}] ", CYAN, True), seg(f"{name}: ", YELLOW, True), seg(thought, TEXT)]
        )
        add(spinner_base + debate_shown, 200)

    # ── 5. Synthesis ─────────────────────────────────────────────────────
    add(spinner_base + debate_shown + [
        None,
        [seg("  ── Analysis from Main Agent ──", SUBTEXT)],
    ], 800)

    synthesis_lines = [
        "SSJ Developer Mode represents a paradigm shift in AI-assisted development.",
        "",
        "Key strengths identified by all personas:",
        "  • Zero-friction workflow: menu-driven UX eliminates command memorization",
        "  • Brainstorm → TODO → Worker pipeline automates the full dev cycle",
        "  • Telegram bridge enables remote async development from any device",
        "  • Force-quit (3× Ctrl+C) ensures the tool never traps the developer",
        "",
        "Recommended next steps saved to brainstorm_outputs/todo_list.txt",
    ]

    synth_base = spinner_base + debate_shown + [
        None,
        [seg("  ── Analysis from Main Agent ──", SUBTEXT)],
        None,
    ]
    streamed = []
    for i, line in enumerate(synthesis_lines):
        streamed.append(text_line(line, 2) if line else None)
        add(synth_base + [x for x in streamed if x is not None], 70 if line else 20)

    add(synth_base + [text_line(l, 2) if l else None for l in synthesis_lines] + [
        None,
        ok_line("TODO list saved to brainstorm_outputs/todo_list.txt"),
    ], 1200)

    # ── 6. Back to SSJ menu ───────────────────────────────────────────────
    add(BANNER + [prompt_line(cmd)] + SSJ_MENU + [None, ssj_prompt(cursor=True)], 1000)

    # ── 7. Type "2" → Show TODO ───────────────────────────────────────────
    add(BANNER + [prompt_line(cmd)] + SSJ_MENU + [None, ssj_prompt("2")], 350)

    todo_display = [
        None,
        [seg("  📋 TODO List (", CYAN), seg("1 done", GREEN, True), seg(" / ", CYAN), seg("4 pending", YELLOW, True), seg("):", CYAN)],
        [seg("  " + "─" * 46, SUBTEXT)],
        [seg("       ✓ ", GREEN), seg("Research existing SSJ menu UX patterns", SUBTEXT)],
        [seg("    1. ○ ", TEXT), seg("Add animated brainstorm spinner with phrases")],
        [seg("    2. ○ ", TEXT), seg("Implement Telegram typing indicator")],
        [seg("    3. ○ ", TEXT), seg("Add /worker task selection by number")],
        [seg("    4. ○ ", TEXT), seg("Write SSJ demo GIF for README")],
        [seg("  " + "─" * 46, SUBTEXT)],
        dim_line("Tip: use Worker (3) with pending task #s e.g. 1,4,6"),
        None,
    ]
    add(BANNER + [prompt_line(cmd)] + SSJ_MENU + [None, ssj_prompt("2")] + todo_display, 1800)

    # SSJ menu re-shown after option 2
    add(BANNER + [prompt_line(cmd)] + SSJ_MENU + [None, ssj_prompt(cursor=True)], 800)

    # ── 8. Type "3" → Worker, select task 4 ──────────────────────────────
    add(BANNER + [prompt_line(cmd)] + SSJ_MENU + [None, ssj_prompt("3")], 350)

    worker_select = [
        [seg("  Task # (Enter for all, or e.g. 1,4,6): ", CYAN), seg("4█", TEXT)],
    ]
    add(BANNER + [prompt_line(cmd)] + SSJ_MENU + [None, ssj_prompt("3")] + worker_select, 600)

    # Worker starts
    worker_base = BANNER + [prompt_line(cmd)] + SSJ_MENU + [None, ssj_prompt("3")] + worker_select + [None]

    add(worker_base + [
        ok_line("Worker starting — 1 task(s) to implement"),
        dim_line("Pending tasks:"),
        [seg("    1. ", SUBTEXT), seg("○ Write SSJ demo GIF for README", TEXT)],
        None,
        [seg("  ── Worker (1/1): ", YELLOW), seg("Write SSJ demo GIF for README", TEXT), seg(" ──", YELLOW)],
        None,
    ], 800)

    tool_section_worker = [
        ok_line("Worker starting — 1 task(s) to implement"),
        dim_line("Pending tasks:"),
        [seg("    1. ", SUBTEXT), seg("○ Write SSJ demo GIF for README", TEXT)],
        None,
        [seg("  ── Worker (1/1): ", YELLOW), seg("Write SSJ demo GIF for README", TEXT), seg(" ──", YELLOW)],
        None,
        claude_header(),
    ]

    add(worker_base + tool_section_worker + [
        tool_line("⚙", "Read", "demos/make_demo.py"),
    ], 500)
    add(worker_base + tool_section_worker + [
        tool_line("⚙", "Read", "demos/make_demo.py"),
        tool_ok("728 lines read"),
        None,
        tool_line("⚙", "Write", "demos/make_ssj_demo.py", MAUVE),
    ], 600)
    add(worker_base + tool_section_worker + [
        tool_line("⚙", "Read", "demos/make_demo.py"),
        tool_ok("728 lines read"),
        None,
        tool_line("⚙", "Write", "demos/make_ssj_demo.py", MAUVE),
        tool_ok("Wrote 312 lines to demos/make_ssj_demo.py"),
        None,
        tool_line("⚙", "Bash", "python3 demos/make_ssj_demo.py"),
    ], 700)
    add(worker_base + tool_section_worker + [
        tool_line("⚙", "Read", "demos/make_demo.py"),
        tool_ok("728 lines read"),
        None,
        tool_line("⚙", "Write", "demos/make_ssj_demo.py", MAUVE),
        tool_ok("Wrote 312 lines to demos/make_ssj_demo.py"),
        None,
        tool_line("⚙", "Bash", "python3 demos/make_ssj_demo.py"),
        tool_ok("→ ssj_demo.gif  (847 KB)"),
        None,
        tool_line("⚙", "Edit", "brainstorm_outputs/todo_list.txt", GREEN),
    ], 600)
    add(worker_base + tool_section_worker + [
        tool_line("⚙", "Read", "demos/make_demo.py"),
        tool_ok("728 lines read"),
        None,
        tool_line("⚙", "Write", "demos/make_ssj_demo.py", MAUVE),
        tool_ok("Wrote 312 lines to demos/make_ssj_demo.py"),
        None,
        tool_line("⚙", "Bash", "python3 demos/make_ssj_demo.py"),
        tool_ok("→ ssj_demo.gif  (847 KB)"),
        None,
        tool_line("⚙", "Edit", "brainstorm_outputs/todo_list.txt", GREEN),
        tool_ok("Marked task as done: - [x] Write SSJ demo GIF for README"),
        None,
        claude_sep(),
    ], 900)

    # ── 9. Worker done, back to SSJ ───────────────────────────────────────
    after_worker = worker_base + tool_section_worker + [
        tool_line("⚙", "Read", "demos/make_demo.py"),
        tool_ok("728 lines read"),
        None,
        tool_line("⚙", "Write", "demos/make_ssj_demo.py", MAUVE),
        tool_ok("Wrote 312 lines to demos/make_ssj_demo.py"),
        None,
        tool_line("⚙", "Bash", "python3 demos/make_ssj_demo.py"),
        tool_ok("→ ssj_demo.gif  (847 KB)"),
        None,
        tool_line("⚙", "Edit", "brainstorm_outputs/todo_list.txt", GREEN),
        tool_ok("Marked task as done: - [x] Write SSJ demo GIF for README"),
        None,
        claude_sep(),
        None,
        ok_line("Worker finished. Run /worker to check remaining tasks."),
        None,
    ]
    add(after_worker, 1200)

    # ── 10. SSJ menu re-shown ─────────────────────────────────────────────
    add(BANNER + [prompt_line(cmd)] + SSJ_MENU + [None, ssj_prompt(cursor=True)], 900)

    # ── 11. Type "0" → Exit ───────────────────────────────────────────────
    add(BANNER + [prompt_line(cmd)] + SSJ_MENU + [None, ssj_prompt("0")], 400)

    add(BANNER + [prompt_line(cmd)] + SSJ_MENU + [
        None,
        ok_line("Exiting SSJ Mode."),
        None,
        prompt_line(cursor=True),
    ], 2000)

    return scenes


# ── Render ─────────────────────────────────────────────────────────────────

def _build_palette():
    theme = [
        BG, SURFACE, TEXT, SUBTEXT,
        CYAN, GREEN, YELLOW, RED, MAUVE, BLUE, PEACH, ORANGE,
        (255, 255, 255), (0, 0, 0),
        (50, 55, 80), (90, 95, 120), (160, 166, 200),
    ]
    flat = []
    for c in theme:
        flat.extend(c)
    while len(flat) < 256 * 3:
        flat.extend((0, 0, 0))
    return flat


def render_gif(output_path="ssj_demo.gif"):
    print("Building SSJ demo scenes...")
    scenes = build_scenes()
    print(f"  {len(scenes)} frames")

    pal_ref = Image.new("P", (1, 1))
    pal_ref.putpalette(_build_palette())

    print("  Rendering frames...")
    rgb_frames, durations = [], []
    for i, (lines, ms) in enumerate(scenes):
        img = draw_frame(lines)
        rgb_frames.append(img)
        durations.append(ms)
        if i % 30 == 0:
            print(f"    {i}/{len(scenes)}...")

    print("  Quantizing palette...")
    p_frames = [f.quantize(palette=pal_ref, dither=0) for f in rgb_frames]

    print(f"Saving → {output_path} ...")
    p_frames[0].save(
        output_path,
        save_all=True,
        append_images=p_frames[1:],
        duration=durations,
        loop=0,
        optimize=False,
    )
    size_kb = os.path.getsize(output_path) // 1024
    print(f"Done! {size_kb} KB — {len(p_frames)} frames")


if __name__ == "__main__":
    docs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")
    out = os.path.join(docs_dir, "ssj_demo.gif")
    render_gif(out)
    print(f"\n→ {out}")
