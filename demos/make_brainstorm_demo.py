#!/usr/bin/env python3
"""
Generate animated GIF demo of little-coder /brainstorm command using PIL.
Simulates the full brainstorm session: agent count prompt → persona generation
→ multi-agent debate → synthesis.
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


def blank_frame():
    return Image.new("RGB", (W, H), BG)


def draw_frame(lines_segments):
    img = blank_frame()
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


# ── Reusable line builders ────────────────────────────────────────────────

BANNER = [
    [seg("╭─ little-coder v3.05.5 ──────────────────────────────────╮", SUBTEXT)],
    [seg("│  ", SUBTEXT), seg("Model: ", SUBTEXT), seg("claude-sonnet-4-6", CYAN, True)],
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


def ok_line(msg):
    return [seg("✓  ", GREEN, True), seg(msg, TEXT)]


def info_line(msg):
    return [seg("  ", SUBTEXT), seg(msg, SUBTEXT)]


def agent_thinking(icon, role):
    return [seg(f"{icon} ", TEXT), seg(role, YELLOW, True), seg(" is thinking...", SUBTEXT)]


def agent_done():
    return [seg("  └─ Perspective captured.", SUBTEXT)]


def claude_header():
    return [
        seg("╭─ Claude ", SUBTEXT),
        seg("●", GREEN),
        seg(" ─────────────────────────────────────────────", SUBTEXT),
    ]


def claude_sep():
    return [seg("╰──────────────────────────────────────────────────────────", SUBTEXT)]


def text_line(t, indent=2):
    return [seg(" " * indent + t, TEXT)]


def dim_line(t, indent=2):
    return [seg(" " * indent + t, SUBTEXT)]


def tool_line(icon, name, arg):
    return [
        seg(f"  {icon}  ", SUBTEXT),
        seg(name, CYAN),
        seg("(", SUBTEXT),
        seg(arg, TEXT),
        seg(")", SUBTEXT),
    ]


def tool_ok(msg):
    return [seg("  ✓ ", GREEN), seg(msg, SUBTEXT)]


# ── Scene builder ─────────────────────────────────────────────────────────

def build_scenes():
    scenes = []

    def add(lines, ms=120):
        scenes.append((lines, ms))

    TOPIC = "medical research funding"
    FILE  = "brainstorm_outputs/brainstorm_20260406_103045.md"

    # ── 0: Banner + empty prompt ─────────────────────────────────────────
    add(BANNER + [prompt_line(cursor=True)], 1000)

    # ── 1: Type /brainstorm medical research funding ──────────────────────
    cmd = f"/brainstorm {TOPIC}"
    for i in range(0, len(cmd) + 1, 3):
        add(BANNER + [prompt_line(cmd[:i], cursor=(i < len(cmd)))], 60)
    add(BANNER + [prompt_line(cmd)], 500)

    # ── 2: Agent count prompt ─────────────────────────────────────────────
    base0 = BANNER + [prompt_line(cmd)]
    add(base0 + [
        [seg("  How many agents? ", SUBTEXT),
         seg("(2-100, default 5)", SUBTEXT),
         seg(" > ", CYAN, True)],
    ], 700)

    # User types "3"
    add(base0 + [
        [seg("  How many agents? ", SUBTEXT),
         seg("(2-100, default 5)", SUBTEXT),
         seg(" > ", CYAN, True),
         seg("3", TEXT)],
    ], 600)

    # ── 3: Generating personas ────────────────────────────────────────────
    base1 = base0 + [
        [seg("  How many agents? ", SUBTEXT),
         seg("(2-100, default 5)", SUBTEXT),
         seg(" > ", CYAN, True),
         seg("3", TEXT)],
    ]
    add(base1 + [info_line("Generating 3 topic-appropriate expert personas...")], 900)

    # ── 4: Session starts ─────────────────────────────────────────────────
    add(base1 + [
        info_line("Generating 3 topic-appropriate expert personas..."),
        ok_line(f"Starting 3-Agent Brainstorming Session on: {TOPIC}"),
        info_line("Generating diverse perspectives..."),
        None,
    ], 700)

    base2 = base1 + [
        info_line("Generating 3 topic-appropriate expert personas..."),
        ok_line(f"Starting 3-Agent Brainstorming Session on: {TOPIC}"),
        info_line("Generating diverse perspectives..."),
        None,
    ]

    # ── 5: Agent 1 thinking → done ───────────────────────────────────────
    add(base2 + [agent_thinking("🩺", "Clinical Trials Director")], 1200)
    add(base2 + [agent_thinking("🩺", "Clinical Trials Director"), agent_done()], 600)

    # ── 6: Agent 2 thinking → done ───────────────────────────────────────
    add(base2 + [
        agent_thinking("🩺", "Clinical Trials Director"), agent_done(),
        agent_thinking("⚖️ ", "Medical Ethics Committee Member"),
    ], 1200)
    add(base2 + [
        agent_thinking("🩺", "Clinical Trials Director"), agent_done(),
        agent_thinking("⚖️ ", "Medical Ethics Committee Member"), agent_done(),
    ], 600)

    # ── 7: Agent 3 thinking → done ───────────────────────────────────────
    add(base2 + [
        agent_thinking("🩺", "Clinical Trials Director"), agent_done(),
        agent_thinking("⚖️ ", "Medical Ethics Committee Member"), agent_done(),
        agent_thinking("💰", "Health Economics Policy Analyst"),
    ], 1200)
    add(base2 + [
        agent_thinking("🩺", "Clinical Trials Director"), agent_done(),
        agent_thinking("⚖️ ", "Medical Ethics Committee Member"), agent_done(),
        agent_thinking("💰", "Health Economics Policy Analyst"), agent_done(),
    ], 700)

    base3 = base2 + [
        agent_thinking("🩺", "Clinical Trials Director"), agent_done(),
        agent_thinking("⚖️ ", "Medical Ethics Committee Member"), agent_done(),
        agent_thinking("💰", "Health Economics Policy Analyst"), agent_done(),
    ]

    # ── 8: Brainstorming complete ─────────────────────────────────────────
    add(base3 + [
        None,
        ok_line(f"Brainstorming complete! Results saved to {FILE}"),
        info_line("Injecting debate results into current session for final analysis..."),
    ], 900)

    # ── 9: Analysis from Main Agent header ───────────────────────────────
    add(base3 + [
        None,
        ok_line(f"Brainstorming complete! Results saved to {FILE}"),
        info_line("Injecting debate results into current session for final analysis..."),
        None,
        [seg("  ── Analysis from Main Agent ──", SUBTEXT)],
        None,
    ], 600)

    base4 = base3 + [
        None,
        ok_line(f"Brainstorming complete! Results saved to {FILE}"),
        None,
        [seg("  ── Analysis from Main Agent ──", SUBTEXT)],
        None,
    ]

    # ── 10: Claude box + Read tool ────────────────────────────────────────
    add(base4 + [claude_header(), tool_line("⚙", "Read", FILE)], 500)
    add(base4 + [claude_header(), tool_line("⚙", "Read", FILE),
                 tool_ok("→ 241 lines (21403 chars)")], 700)

    # ── 11: Stream synthesis response ────────────────────────────────────
    synthesis = [
        "## Master Plan — Medical Research Funding",
        "",
        "**Key Consensus (all 3 experts agree):**",
        "  1. Shift from statistical to clinical significance (MCID, QALYs)",
        "  2. Dynamic informed consent + federated data privacy",
        "  3. Real-world evidence (RWE) as standard post-approval practice",
        "",
        "**Phase 1 (0-12 mo):** Governance framework — registered reports,",
        "  dynamic consent platform, social-value ROI model.",
        "",
        "**Phase 2 (12-24 mo):** Pilot in 3 disease areas — decentralized",
        "  trials, patient co-design, SDOH stratified analysis.",
        "",
        "**Phase 3 (24-36 mo):** Scale — RWE monitoring, innovation-pull",
        "  payment, cross-institutional data governance alliance.",
    ]
    tool_sec = [
        tool_line("⚙", "Read", FILE),
        tool_ok("→ 241 lines (21403 chars)"),
        None,
        [seg("│ ", SUBTEXT)],
    ]
    streamed = []
    for line in synthesis:
        streamed.append(text_line(line, 2))
        add(base4 + [claude_header()] + tool_sec + streamed, 70 if line else 30)

    add(base4 + [claude_header()] + tool_sec +
        [text_line(l, 2) for l in synthesis] + [claude_sep()], 1000)

    # ── 12: Synthesis saved ───────────────────────────────────────────────
    add(base4 + [claude_header()] + tool_sec +
        [text_line(l, 2) for l in synthesis] + [claude_sep()] +
        [None, ok_line(f"Synthesis appended to {FILE}")], 1200)

    # ── 13: New prompt ────────────────────────────────────────────────────
    add(base4 + [claude_header()] + tool_sec +
        [text_line(l, 2) for l in synthesis] + [claude_sep()] +
        [None, ok_line(f"Synthesis appended to {FILE}"),
         None, prompt_line(cursor=True)], 2500)

    return scenes


# ── Palette + render ──────────────────────────────────────────────────────

def _build_palette():
    theme = [
        BG, SURFACE, TEXT, SUBTEXT,
        CYAN, GREEN, YELLOW, RED, MAUVE, BLUE, PEACH,
        (255, 255, 255), (0, 0, 0),
        (50, 55, 80), (90, 95, 120), (160, 166, 200),
    ]
    flat = []
    for c in theme:
        flat.extend(c)
    while len(flat) < 256 * 3:
        flat.extend((0, 0, 0))
    return flat


def render_gif(output_path):
    print("Building scenes...")
    scenes = build_scenes()
    print(f"  {len(scenes)} scenes")

    pal_ref = Image.new("P", (1, 1))
    pal_ref.putpalette(_build_palette())

    print("  Rendering frames...")
    rgb_frames, durations = [], []
    for i, (lines, ms) in enumerate(scenes):
        rgb_frames.append(draw_frame(lines))
        durations.append(ms)
        if i % 20 == 0:
            print(f"  {i}/{len(scenes)}...")

    print("  Quantizing...")
    p_frames = [f.quantize(palette=pal_ref, dither=0) for f in rgb_frames]

    print(f"Saving → {output_path}  ({len(p_frames)} frames)")
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


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "docs", "brainstorm_demo.gif")
    render_gif(out)
    print(f"\nGIF saved: {out}")
