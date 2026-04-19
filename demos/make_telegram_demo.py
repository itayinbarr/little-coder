#!/usr/bin/env python3
"""
Generate animated GIF demo of little-coder Telegram Bridge.
Shows: setup → auto-start → incoming messages → tool calls → response → stop
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
TEAL    = ( 48, 213, 200)   # Telegram brand teal

W, H = 960, 720
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
FONT_SIZE = 14
LINE_H    = 20
PAD_X     = 18
PAD_Y     = 16

# Phone panel dimensions
PHONE_X  = 560   # left edge of phone panel
PHONE_W  = 380
PHONE_H  = 560
PHONE_Y  = 80
PHONE_R  = 24    # corner radius

def make_font(size=FONT_SIZE, bold=False):
    path = FONT_BOLD if bold else FONT_PATH
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

FONT   = make_font()
FONT_B = make_font(bold=True)
FONT_SM = make_font(FONT_SIZE - 2)

def seg(t, c=TEXT, b=False):
    return (t, c, b)

def render_line(draw, y, segments, x_start=PAD_X):
    x = x_start
    for text, color, bold in segments:
        font = FONT_B if bold else FONT
        draw.text((x, y), text, font=font, fill=color)
        x += font.getlength(text)
    return y + LINE_H


# ── Phone UI helpers ─────────────────────────────────────────────────────

def draw_phone(img, chat_messages):
    """
    Draw a minimal phone-style Telegram chat panel on the right.
    chat_messages: list of (sender, text, color)
      sender = "user" | "bot"
    """
    d = ImageDraw.Draw(img)

    # Phone background rounded rect (simulate with filled rect + circles)
    px, py, pw, ph = PHONE_X, PHONE_Y, PHONE_W, PHONE_H
    phone_bg = (22, 33, 62)       # dark navy
    header_bg = (33, 150, 243)    # Telegram blue
    bubble_user = (33, 150, 243)  # blue bubbles (user)
    bubble_bot  = (37, 37, 50)    # dark bubbles (bot)

    # Phone background
    d.rounded_rectangle([px, py, px+pw, py+ph], radius=PHONE_R, fill=phone_bg)

    # Header bar
    header_h = 48
    d.rounded_rectangle([px, py, px+pw, py+header_h], radius=PHONE_R, fill=header_bg)
    d.rectangle([px, py+PHONE_R, px+pw, py+header_h], fill=header_bg)  # fill bottom corners

    # Bot avatar circle
    av_x, av_y, av_r = px+16, py+14, 14
    d.ellipse([av_x, av_y, av_x+av_r*2, av_y+av_r*2], fill=(255, 255, 255, 180))
    d.text((av_x+5, av_y+3), "🤖", font=FONT_SM, fill=(30, 30, 46))

    # Bot name
    d.text((px+52, py+10), "@little-coder_bot", font=FONT_B, fill=(255, 255, 255))
    d.text((px+52, py+27), "online", font=FONT_SM, fill=(178, 223, 255))

    # Messages area
    msg_y = py + header_h + 10
    max_msg_y = py + ph - 50  # leave room for input bar

    for sender, text, _color in chat_messages:
        is_user = (sender == "user")
        bubble_color = bubble_user if is_user else bubble_bot
        text_color   = (255, 255, 255) if is_user else TEXT

        # Word-wrap text to ~32 chars
        words = text.split()
        lines_wrapped = []
        cur = ""
        for w in words:
            if len(cur) + len(w) + 1 > 32:
                if cur:
                    lines_wrapped.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur:
            lines_wrapped.append(cur)

        bubble_h = len(lines_wrapped) * 18 + 12
        bubble_w = max(FONT.getlength(l) for l in lines_wrapped) + 20

        if is_user:
            bx = px + pw - bubble_w - 10
        else:
            bx = px + 10

        if msg_y + bubble_h > max_msg_y:
            break

        d.rounded_rectangle([bx, msg_y, bx+bubble_w, msg_y+bubble_h], radius=10, fill=bubble_color)
        for li, ln in enumerate(lines_wrapped):
            d.text((bx+10, msg_y+6+li*18), ln, font=FONT_SM, fill=text_color)

        msg_y += bubble_h + 6

    # Input bar
    input_y = py + ph - 44
    d.rounded_rectangle([px+8, input_y, px+pw-8, py+ph-8], radius=20, fill=(45, 45, 65))
    d.text((px+22, input_y+10), "Message...", font=FONT_SM, fill=SUBTEXT)

    # Thin divider between terminal and phone
    d.line([(PHONE_X - 14, PHONE_Y), (PHONE_X - 14, PHONE_Y + PHONE_H)], fill=SURFACE, width=1)


# ── Terminal helpers ─────────────────────────────────────────────────────

def draw_frame(lines_segments, chat_messages=None):
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
    if chat_messages is not None:
        draw_phone(img, chat_messages)
    return img


BANNER_TG = [
    [seg("╭─ little-coder ─────────────────────────────────────────╮", SUBTEXT)],
    [seg("│  ", SUBTEXT), seg("Model: ", SUBTEXT), seg("claude-opus-4-6", CYAN, True)],
    [seg("│  ", SUBTEXT), seg("Permissions: ", SUBTEXT), seg("auto", YELLOW, True),
     seg("  flags: [", SUBTEXT), seg("telegram", TEAL, True), seg("]", SUBTEXT)],
    [seg("│  Type /help for commands, Ctrl+C to cancel                 │", SUBTEXT)],
    [seg("╰────────────────────────────────────────────────────────────╯", SUBTEXT)],
    None,
]

def prompt_line(text="", cursor=False):
    cur = "█" if cursor else ""
    return [seg("[little-coder] ", SUBTEXT), seg("» ", CYAN, True), seg(text + cur, TEXT)]

def ok_line(t):
    return [seg("  ✓ ", GREEN, True), seg(t, TEXT)]

def info_line(t):
    return [seg("  ℹ ", CYAN), seg(t, SUBTEXT)]

def warn_line(t):
    return [seg("  ⚠ ", YELLOW), seg(t, SUBTEXT)]

def dim_line(t, indent=4):
    return [seg(" " * indent + t, SUBTEXT)]

def claude_header():
    return [seg("╭─ Claude ", SUBTEXT), seg("●", GREEN), seg(" ─────────────────────────────────────────────", SUBTEXT)]

def claude_sep():
    return [seg("╰──────────────────────────────────────────────────────────", SUBTEXT)]

def tool_line(icon, name, arg, color=CYAN):
    return [seg(f"  {icon}  ", SUBTEXT), seg(name, color),
            seg("(", SUBTEXT), seg(arg, TEXT), seg(")", SUBTEXT)]

def tool_ok(msg):
    return [seg("  ✓ ", GREEN), seg(msg, SUBTEXT)]

def text_line(t, indent=2):
    return [seg(" " * indent + t, TEXT)]

def tg_incoming(text):
    """Telegram incoming message line shown in terminal."""
    return [seg("\n", TEXT), seg("  📩 Telegram: ", TEAL, True), seg(text, TEXT)]

def tg_sent(preview):
    return [seg("  ✈  ", TEAL), seg("Response sent → ", SUBTEXT), seg(preview, SUBTEXT)]

SPINNER = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]


# ── Scene builder ─────────────────────────────────────────────────────────

def build_scenes():
    scenes = []

    def add(lines, ms=120, chat=None):
        scenes.append((lines, ms, chat))

    # ── 0: Banner — telegram flag visible, auto-started ──────────────────
    add(BANNER_TG + [
        ok_line("Telegram bridge started (auto). Bot: @little-coder_bot"),
        info_line("Send messages to your bot — they'll be processed here."),
        info_line("Stop with /telegram stop or send /stop in Telegram."),
        None,
        prompt_line(cursor=True),
    ], 1200, chat=[])

    # ── 1: /telegram status ───────────────────────────────────────────────
    base = BANNER_TG + [
        ok_line("Telegram bridge started (auto). Bot: @little-coder_bot"),
        info_line("Send messages to your bot — they'll be processed here."),
        info_line("Stop with /telegram stop or send /stop in Telegram."),
        None,
    ]
    cmd_status = "/telegram status"
    for i in range(0, len(cmd_status) + 1, 3):
        add(base + [prompt_line(cmd_status[:i], cursor=(i < len(cmd_status)))], 60, chat=[])
    add(base + [prompt_line(cmd_status)], 300, chat=[])

    add(base + [
        prompt_line(cmd_status),
        None,
        ok_line("Telegram bridge is running.  Bot: @little-coder_bot  Chat ID: 123456789"),
        None,
        prompt_line(cursor=True),
    ], 1000, chat=[])

    # phone shows "online" with bot greeting
    phone_init = [
        ("bot", "🟢 little-coder is online. Send me a message and I'll process it.", TEAL),
    ]
    add(base + [prompt_line(cursor=True)], 800, chat=phone_init)

    # ── 2: First message from phone — "What files are in this project?" ──
    # Phone shows user typing
    phone_q1_typing = phone_init + [("user", "What files are in this project?", BLUE)]

    add(base + [
        prompt_line(cursor=True),
        None,
        [seg("  📩 Telegram: ", TEAL, True), seg("What files are in this project?", TEXT)],
    ], 900, chat=phone_q1_typing)

    # ── 3: Typing indicator + model processes ─────────────────────────────
    tg_base = base + [
        prompt_line(cursor=False),
        None,
        [seg("  📩 Telegram: ", TEAL, True), seg("What files are in this project?", TEXT)],
        None,
    ]

    for si in range(6):
        spin = SPINNER[si % len(SPINNER)]
        add(tg_base + [
            [seg(f"  {spin} ", TEAL), seg("sending typing indicator...", SUBTEXT)],
        ], 200, chat=phone_q1_typing)

    add(tg_base + [
        [seg("  ✓ ", GREEN), seg("typing indicator sent", SUBTEXT)],
        None,
        claude_header(),
        tool_line("⚙", "Glob", "**/*", CYAN),
    ], 500, chat=phone_q1_typing)

    add(tg_base + [
        [seg("  ✓ ", GREEN), seg("typing indicator sent", SUBTEXT)],
        None,
        claude_header(),
        tool_line("⚙", "Glob", "**/*", CYAN),
        tool_ok("12 files matched"),
    ], 600, chat=phone_q1_typing)

    resp1_lines = [
        "Here are the files in this project:",
        "",
        "  little_coder.py   — Main REPL + slash commands",
        "  agent.py         — Core agent loop",
        "  tools.py         — Built-in tools (Read/Write/Edit/Bash…)",
        "  providers.py     — API provider abstraction",
        "  config.py        — Configuration management",
        "  context.py       — System prompt builder",
        "  memory/          — Persistent memory system",
        "  mcp/             — MCP client integration",
    ]

    tool_done = tg_base + [
        [seg("  ✓ ", GREEN), seg("typing indicator sent", SUBTEXT)],
        None,
        claude_header(),
        tool_line("⚙", "Glob", "**/*", CYAN),
        tool_ok("12 files matched"),
        None,
        [seg("│ ", SUBTEXT)],
    ]

    streamed = []
    for i, line in enumerate(resp1_lines):
        streamed.append(text_line(line, 2) if line else None)
        add(tool_done + [x for x in streamed if x is not None], 60, chat=phone_q1_typing)

    add(tool_done + [text_line(l, 2) if l else None for l in resp1_lines] + [claude_sep()], 500, chat=phone_q1_typing)

    # ── 4: Response sent to Telegram ─────────────────────────────────────
    phone_r1 = phone_q1_typing + [("bot", "Here are the files in this project: little_coder.py, agent.py, tools.py, providers.py, config.py …", GREEN)]

    after_r1 = tg_base + [
        [seg("  ✓ ", GREEN), seg("typing indicator sent", SUBTEXT)],
        None,
        claude_header(),
        tool_line("⚙", "Glob", "**/*", CYAN),
        tool_ok("12 files matched"),
        None,
        [seg("│ ", SUBTEXT)],
    ] + [text_line(l, 2) if l else None for l in resp1_lines] + [claude_sep(), None]

    add(after_r1 + [tg_sent("Here are the files in this project...")], 900, chat=phone_r1)
    add(after_r1 + [tg_sent("Here are the files in this project..."), None, prompt_line(cursor=True)], 800, chat=phone_r1)

    # ── 5: Second message — slash command /cost via Telegram ──────────────
    phone_q2 = phone_r1 + [("user", "/cost", BLUE)]

    add(after_r1 + [
        prompt_line(cursor=False),
        None,
        [seg("  📩 Telegram: ", TEAL, True), seg("/cost", TEXT), seg("  (slash command passthrough)", SUBTEXT)],
    ], 900, chat=phone_q2)

    cost_base = after_r1 + [
        prompt_line(cursor=False),
        None,
        [seg("  📩 Telegram: ", TEAL, True), seg("/cost", TEXT), seg("  (slash command passthrough)", SUBTEXT)],
        None,
    ]

    cost_lines = [
        [seg("  Input tokens:  ", CYAN), seg("3,241", TEXT, True)],
        [seg("  Output tokens: ", CYAN), seg("487",   TEXT, True)],
        [seg("  Est. cost:     ", CYAN), seg("$0.0521 USD", GREEN, True)],
    ]

    add(cost_base + cost_lines, 700, chat=phone_q2)

    phone_cost = phone_q2 + [("bot", "Input: 3,241 tokens | Output: 487 tokens | Cost: $0.0521 USD", GREEN)]
    add(cost_base + cost_lines + [None, tg_sent("Input: 3,241 tokens | Output: 487 …")], 900, chat=phone_cost)
    add(cost_base + cost_lines + [None, tg_sent("Input: 3,241 tokens | Output: 487 …"), None, prompt_line(cursor=True)], 800, chat=phone_cost)

    # ── 6: Third message — code question ─────────────────────────────────
    phone_q3 = phone_cost + [("user", "How does the /brainstorm command work?", BLUE)]

    q3_base = after_r1 + [
        prompt_line(cursor=False),
        None,
        [seg("  📩 Telegram: ", TEAL, True), seg("How does the /brainstorm command work?", TEXT)],
        None,
    ]

    for si in range(5):
        spin = SPINNER[si % len(SPINNER)]
        add(q3_base + [
            [seg(f"  {spin} ", TEAL), seg("sending typing indicator...", SUBTEXT)],
        ], 180, chat=phone_q3)

    add(q3_base + [
        [seg("  ✓ ", GREEN), seg("typing indicator sent", SUBTEXT)],
        None,
        claude_header(),
        tool_line("⚙", "Grep", "def cmd_brainstorm", MAUVE),
        tool_ok("Found in little_coder.py:480"),
        None,
        tool_line("⚙", "Read", "little_coder.py:480-550", CYAN),
        tool_ok("71 lines read"),
    ], 700, chat=phone_q3)

    resp3_words = "/brainstorm starts a multi-persona AI debate. It generates expert personas, runs parallel debate rounds, then synthesizes a Master Plan saved to brainstorm_outputs/. A todo_list.txt is auto-created from the plan."
    resp3_segs = []
    words = resp3_words.split()
    shown = []
    for wi, w in enumerate(words):
        shown.append(w)
        resp3_segs = [text_line(" ".join(shown), 2)]
        add(q3_base + [
            [seg("  ✓ ", GREEN), seg("typing indicator sent", SUBTEXT)],
            None,
            claude_header(),
            tool_line("⚙", "Grep", "def cmd_brainstorm", MAUVE),
            tool_ok("Found in little_coder.py:480"),
            None,
            tool_line("⚙", "Read", "little_coder.py:480-550", CYAN),
            tool_ok("71 lines read"),
            None,
            [seg("│ ", SUBTEXT)],
        ] + resp3_segs, 45, chat=phone_q3)

    phone_r3 = phone_q3 + [("bot", "/brainstorm starts a multi-persona AI debate and synthesizes a Master Plan…", GREEN)]

    add(q3_base + [
        [seg("  ✓ ", GREEN), seg("typing indicator sent", SUBTEXT)],
        None,
        claude_header(),
        tool_line("⚙", "Grep", "def cmd_brainstorm", MAUVE),
        tool_ok("Found in little_coder.py:480"),
        None,
        tool_line("⚙", "Read", "little_coder.py:480-550", CYAN),
        tool_ok("71 lines read"),
        None,
        [seg("│ ", SUBTEXT)],
        text_line(resp3_words, 2),
        claude_sep(),
        None,
        tg_sent("/brainstorm starts a multi-persona AI debate…"),
        None,
        prompt_line(cursor=True),
    ], 1000, chat=phone_r3)

    # ── 7: /stop from Telegram ────────────────────────────────────────────
    phone_stop = phone_r3 + [("user", "/stop", BLUE)]
    phone_stopped = phone_stop + [("bot", "🔴 Telegram bridge stopped.", RED)]

    stop_base = q3_base + [
        [seg("  ✓ ", GREEN), seg("typing indicator sent", SUBTEXT)],
        None,
        claude_header(),
        tool_line("⚙", "Grep", "def cmd_brainstorm", MAUVE),
        tool_ok("Found in little_coder.py:480"),
        None,
        tool_line("⚙", "Read", "little_coder.py:480-550", CYAN),
        tool_ok("71 lines read"),
        None,
        [seg("│ ", SUBTEXT)],
        text_line(resp3_words, 2),
        claude_sep(),
        None,
        tg_sent("/brainstorm starts a multi-persona AI debate…"),
        None,
        prompt_line(cursor=False),
        None,
        [seg("  📩 Telegram: ", TEAL, True), seg("/stop", TEXT)],
        None,
    ]

    add(stop_base + [
        warn_line("Telegram bridge stopped by remote /stop command."),
        None,
        prompt_line(cursor=True),
    ], 2000, chat=phone_stopped)

    return scenes


# ── Render ─────────────────────────────────────────────────────────────────

def _build_palette():
    theme = [
        BG, SURFACE, TEXT, SUBTEXT,
        CYAN, GREEN, YELLOW, RED, MAUVE, BLUE, TEAL,
        (255, 255, 255), (0, 0, 0),
        (22, 33, 62),    # phone bg
        (33, 150, 243),  # telegram blue
        (37, 37, 50),    # bot bubble
        (45, 45, 65),    # input bar
        (178, 223, 255), # online text
        (50, 55, 80), (90, 95, 120),
    ]
    flat = []
    for c in theme:
        flat.extend(c)
    while len(flat) < 256 * 3:
        flat.extend((0, 0, 0))
    return flat


def render_gif(output_path="telegram_demo.gif"):
    print("Building Telegram demo scenes...")
    scenes = build_scenes()
    print(f"  {len(scenes)} frames")

    pal_ref = Image.new("P", (1, 1))
    pal_ref.putpalette(_build_palette())

    print("  Rendering frames...")
    rgb_frames, durations = [], []
    for i, (lines, ms, chat) in enumerate(scenes):
        img = draw_frame(lines, chat_messages=chat)
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
    out = os.path.join(docs_dir, "telegram_demo.gif")
    render_gif(out)
    print(f"\n→ {out}")
