#!/usr/bin/env python3
"""
Generate animated GIF demo of little-coder proactive / background-event feature.
Shows: timer reminder set → idle at prompt → [Background Event Triggered] →
Claude fires reminder → user asks again → second reminder fires.
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
    [seg("  Active: ", SUBTEXT), seg("proactive", GREEN, True)],
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


def bg_event_line():
    return [seg("\n[Background Event Triggered]", YELLOW, True)]


# ── Scene builder ─────────────────────────────────────────────────────────

def build_scenes():
    scenes = []

    def add(lines, ms=120):
        scenes.append((lines, ms))

    # ── 0: Banner + idle prompt ──────────────────────────────────────────
    add(BANNER + [prompt_line(cursor=True)], 1000)

    # ── 1: User types reminder request ──────────────────────────────────
    msg1 = "remind me to call my mom in 1 minute"
    for i in range(0, len(msg1) + 1, 3):
        add(BANNER + [prompt_line(msg1[:i], cursor=(i < len(msg1)))], 55)
    add(BANNER + [prompt_line(msg1)], 400)

    # ── 2: Claude responds with SleepTimer ───────────────────────────────
    pre1 = BANNER + [prompt_line(msg1)]
    add(pre1 + [None, claude_header(), tool_line("⚙", "SleepTimer", "60")], 600)
    add(pre1 + [None, claude_header(),
                tool_line("⚙", "SleepTimer", "60"),
                tool_ok("→ 1 lines (134 chars)")], 500)

    resp1 = [
        "Got it! I've set a 1-minute reminder for you.",
        "",
        "I'll notify you in 60 seconds to call your mom.",
    ]
    tool1 = [
        tool_line("⚙", "SleepTimer", "60"),
        tool_ok("→ 1 lines (134 chars)"),
        None,
        [seg("│ ", SUBTEXT)],
    ]
    streamed1 = []
    for line in resp1:
        streamed1.append(text_line(line, 2))
        add(pre1 + [None, claude_header()] + tool1 + streamed1, 70 if line else 30)
    add(pre1 + [None, claude_header()] + tool1 +
        [text_line(l, 2) for l in resp1] + [claude_sep()], 600)

    # ── 3: New prompt — user idle ────────────────────────────────────────
    after1 = (pre1 + [None, claude_header()] + tool1 +
               [text_line(l, 2) for l in resp1] + [claude_sep(), None])
    add(after1 + [prompt_line(cursor=True)], 2500)

    # ── 4: Background event fires ────────────────────────────────────────
    add(after1 + [
        [seg("", SUBTEXT)],
        [seg("[Background Event Triggered]", YELLOW, True)],
    ], 800)

    add(after1 + [
        [seg("", SUBTEXT)],
        [seg("[Background Event Triggered]", YELLOW, True)],
        None,
        claude_header(),
    ], 400)

    fire1 = [
        "The 1-minute timer has finished.",
        "",
        "Time to call your mom! Don't forget — she'll love hearing from you.",
        "",
        "Let me know if you need another reminder or anything else!",
    ]
    streamed2 = []
    for line in fire1:
        streamed2.append(text_line(line, 2))
        add(after1 + [
            [seg("", SUBTEXT)],
            [seg("[Background Event Triggered]", YELLOW, True)],
            None,
            claude_header(),
        ] + streamed2, 70 if line else 30)

    fired1_base = (after1 + [
        [seg("", SUBTEXT)],
        [seg("[Background Event Triggered]", YELLOW, True)],
        None,
        claude_header(),
    ] + [text_line(l, 2) for l in fire1] + [claude_sep()])

    add(fired1_base, 600)

    # ── 5: Prompt redrawn after background event ─────────────────────────
    add(fired1_base + [
        None,
        prompt_line(cursor=True),
    ], 1200)

    # ── 6: User types "still busy, remind me again" ──────────────────────
    msg2 = "still busy, remind me again in 1 minute"
    for i in range(0, len(msg2) + 1, 3):
        add(fired1_base + [None, prompt_line(msg2[:i], cursor=(i < len(msg2)))], 55)
    add(fired1_base + [None, prompt_line(msg2)], 400)

    # ── 7: Claude sets another timer ─────────────────────────────────────
    pre2 = fired1_base + [None, prompt_line(msg2)]
    add(pre2 + [None, claude_header(), tool_line("⚙", "SleepTimer", "60")], 500)
    add(pre2 + [None, claude_header(),
                tool_line("⚙", "SleepTimer", "60"),
                tool_ok("→ 1 lines (134 chars)")], 500)

    resp2 = [
        "No problem! Another 1-minute reminder has been set.",
        "",
        "Take your time — I'll remind you again in 60 seconds.",
    ]
    tool2 = [
        tool_line("⚙", "SleepTimer", "60"),
        tool_ok("→ 1 lines (134 chars)"),
        None,
        [seg("│ ", SUBTEXT)],
    ]
    streamed3 = []
    for line in resp2:
        streamed3.append(text_line(line, 2))
        add(pre2 + [None, claude_header()] + tool2 + streamed3, 70 if line else 30)
    add(pre2 + [None, claude_header()] + tool2 +
        [text_line(l, 2) for l in resp2] + [claude_sep()], 600)

    # ── 8: Idle at prompt again ──────────────────────────────────────────
    after2 = (pre2 + [None, claude_header()] + tool2 +
               [text_line(l, 2) for l in resp2] + [claude_sep(), None])
    add(after2 + [prompt_line(cursor=True)], 2000)

    # ── 9: Second background event fires ────────────────────────────────
    add(after2 + [
        [seg("", SUBTEXT)],
        [seg("[Background Event Triggered]", YELLOW, True)],
    ], 700)

    add(after2 + [
        [seg("", SUBTEXT)],
        [seg("[Background Event Triggered]", YELLOW, True)],
        None,
        claude_header(),
    ], 400)

    fire2 = [
        "Timer finished again — time to call your mom!",
        "",
        "I'll keep reminding you until you're ready. Just say the word!",
    ]
    streamed4 = []
    for line in fire2:
        streamed4.append(text_line(line, 2))
        add(after2 + [
            [seg("", SUBTEXT)],
            [seg("[Background Event Triggered]", YELLOW, True)],
            None,
            claude_header(),
        ] + streamed4, 70 if line else 30)

    fired2_base = (after2 + [
        [seg("", SUBTEXT)],
        [seg("[Background Event Triggered]", YELLOW, True)],
        None,
        claude_header(),
    ] + [text_line(l, 2) for l in fire2] + [claude_sep()])

    add(fired2_base, 600)

    # ── 10: Final prompt ─────────────────────────────────────────────────
    add(fired2_base + [None, prompt_line(cursor=True)], 2500)

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
                       "..", "docs", "proactive_demo.gif")
    render_gif(out)
    print(f"\nGIF saved: {out}")
