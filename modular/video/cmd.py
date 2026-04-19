"""
Video slash-command wizard for little-coder.

This module is the REPL-facing layer of the video plugin.
It contains the interactive wizard (cmd_video) and helpers,
but no pipeline logic — those live in video/pipeline.py etc.

COMMAND_DEFS is the plug-in interface: little_coder.py discovers
commands from this dict so the module can be loaded optionally.
"""
from __future__ import annotations

import os
import sys

# ── Minimal ANSI helpers (self-contained, no import from little_coder) ────────
_C = {
    "cyan":    "\033[36m", "green":  "\033[32m", "yellow": "\033[33m",
    "red":     "\033[31m", "blue":   "\033[34m", "magenta":"\033[35m",
    "bold":    "\033[1m",  "dim":    "\033[2m",  "reset":  "\033[0m",
}

def _clr(text: str, *keys: str) -> str:
    return "".join(_C[k] for k in keys) + str(text) + _C["reset"]

def _info(msg: str):  print(_clr(msg, "cyan"))
def _ok(msg: str):    print(_clr(msg, "green"))
def _warn(msg: str):  print(_clr(f"Warning: {msg}", "yellow"))
def _err(msg: str):   print(_clr(f"Error: {msg}", "red"), file=sys.stderr)


def _ask(prompt: str, config) -> str:
    """Thin wrapper: use ask_input_interactive from tools if available."""
    try:
        from tools import ask_input_interactive
        return ask_input_interactive(prompt, config)
    except ImportError:
        import re as _re
        return input(_re.sub(r'(\x1b\[[0-9;]*m)', r'\001\1\002', prompt))


# ── Language table ─────────────────────────────────────────────────────────────
VIDEO_LANGUAGES = [
    # (label,           whisper_code, edge_voice,                  story_instruction)
    ("🇨🇳 Chinese",    "zh",  "zh-CN-YunxiNeural",   "Write the story ENTIRELY in Simplified Chinese (中文)."),
    ("🇺🇸 English",    "en",  "en-US-GuyNeural",      "Write the story ENTIRELY in English."),
    ("🇪🇸 Spanish",    "es",  "es-ES-AlvaroNeural",   "Write the story ENTIRELY in Spanish."),
    ("🇯🇵 Japanese",   "ja",  "ja-JP-KeitaNeural",    "Write the story ENTIRELY in Japanese (日本語)."),
    ("🇰🇷 Korean",     "ko",  "ko-KR-InJoonNeural",   "Write the story ENTIRELY in Korean (한국어)."),
    ("🇫🇷 French",     "fr",  "fr-FR-HenriNeural",    "Write the story ENTIRELY in French."),
    ("🇩🇪 German",     "de",  "de-DE-ConradNeural",   "Write the story ENTIRELY in German."),
    ("🇵🇹 Portuguese", "pt",  "pt-BR-AntonioNeural",  "Write the story ENTIRELY in Portuguese."),
    ("🇷🇺 Russian",    "ru",  "ru-RU-DmitryNeural",   "Write the story ENTIRELY in Russian."),
    ("🌐 Auto",        "auto","en-US-GuyNeural",       ""),
]

_VP_BACK = -1   # sentinel: user wants to go back
_VP_QUIT = -2   # sentinel: user wants to quit


def _video_pick(prompt: str, options: list[str], config, default: int | None = None) -> int:
    """Show a numbered list, return 0-based index.
    Returns _VP_BACK (-1) on 'b', _VP_QUIT (-2) on 'q'.
    """
    for i, opt in enumerate(options, 1):
        print(f"{_clr(f'  {i:>2}.', 'cyan')} {opt}")
    hint = _clr(f"  [{'Enter=' + str(default) if default else 'Enter=1'}  b=back  q=quit]", "dim")
    print(hint)
    try:
        raw = _ask(_clr(f"  {prompt}: ", "cyan"), config).strip().lower()
    except (KeyboardInterrupt, EOFError):
        return _VP_QUIT
    if raw in ("b", "back"):
        return _VP_BACK
    if raw in ("q", "quit", "exit", "0"):
        return _VP_QUIT
    if not raw and default:
        return default - 1
    if raw.isdigit():
        n = int(raw) - 1
        if 0 <= n < len(options):
            return n
    return (default - 1) if default else 0


def _detect_lang(text: str) -> int:
    """Return index into VIDEO_LANGUAGES based on script detection, default 1 (English)."""
    if not text:
        return 1
    cjk   = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    kana  = sum(1 for c in text if '\u3040' <= c <= '\u30ff')
    hangu = sum(1 for c in text if '\uac00' <= c <= '\ud7a3')
    cyr   = sum(1 for c in text if '\u0400' <= c <= '\u04ff')
    total = max(len(text), 1)
    if cjk / total > 0.05:   return 0  # Chinese
    if kana / total > 0.02:  return 3  # Japanese
    if hangu / total > 0.02: return 4  # Korean
    if cyr / total > 0.05:   return 8  # Russian
    return 1  # English


# ── Public command ─────────────────────────────────────────────────────────────

def cmd_video(args: str, _state, config) -> bool:
    """AI-powered viral video content factory — full number-selection wizard.

    Usage:
      /video [topic]          Launch interactive wizard
      /video status           Show dependency status
      /video --source <dir>   Pre-load images/audio/text from a folder
    """
    from . import check_video_deps
    from .niches import CONTENT_NICHES

    sub = args.strip().split()[0].lower() if args.strip() else ""

    # ── /video status ─────────────────────────────────────────────────────────
    if sub == "status":
        deps = check_video_deps()
        print(_clr("\n  Video Pipeline Dependencies\n", "bold"))
        dep_rows = [
            ("ffmpeg",         deps.get("ffmpeg"),         "Video assembly"),
            ("ffprobe",        deps.get("ffprobe"),         "Audio duration probe"),
            ("edge-tts",       deps.get("edge_tts"),        "Free TTS  →  pip install edge-tts"),
            ("faster-whisper", deps.get("faster_whisper"),  "Subtitles →  pip install faster-whisper"),
            ("playwright",     deps.get("playwright"),      "Gemini Web images →  pip install playwright"),
            ("Pillow",         deps.get("pillow"),          "Image tools →  pip install Pillow"),
            ("imageio-ffmpeg", deps.get("ffmpeg"),          "No-sudo ffmpeg →  pip install imageio-ffmpeg"),
        ]
        for name, flag, note in dep_rows:
            mark = _clr("✓", "green") if flag else _clr("✗", "red")
            print(f"  {mark}  {name:<18} {note}")
        print()
        for key, label in [("GEMINI_API_KEY", "Gemini TTS + story"), ("ELEVENLABS_API_KEY", "ElevenLabs TTS")]:
            val = os.getenv(key, "")
            mark = _clr("✓", "green") if val else _clr("—", "dim")
            print(f"  {mark}  {key:<22} {label}")
        print()
        return True

    # ── Parse --source flag ────────────────────────────────────────────────────
    source_dir: str | None = None
    topic_parts: list[str] = []
    tokens = args.split()
    i = 0
    while i < len(tokens):
        if tokens[i] == "--source" and i + 1 < len(tokens):
            source_dir = os.path.expanduser(tokens[i + 1]); i += 2
        elif tokens[i] == "status":
            i += 1
        else:
            topic_parts.append(tokens[i]); i += 1
    topic_from_args = " ".join(topic_parts).strip()

    is_tg = config.get("_telegram_incoming", False)

    # ════════════════════════════════════════════════════════════════════════════
    # WIZARD — step-based loop with back navigation
    # ════════════════════════════════════════════════════════════════════════════
    niche_keys = list(CONTENT_NICHES.keys())

    print(_clr("\n╭─ 🎬 Video Content Factory ──────────────────────────────╮", "bold"))
    print(_clr("│  Enter=Auto on every step  ·  b=back  ·  q=quit         │", "dim"))
    print(_clr("╰─────────────────────────────────────────────────────────╯\n", "bold"))

    W: dict = {
        "content_mode": "ai",
        "script_text": "",
        "topic": topic_from_args,
        "source_dir": source_dir,
        "lang_idx": None,
        "lang_name": "",
        "niche_name": None,
        "is_short": False,
        "duration_min": 2.0,
        "tts_engine": "auto",
        "image_engine": "auto",
        "quality": "medium",
        "subtitle_mode": "auto",
        "subtitle_text": "",
        "output_dir": None,
    }

    STEP_NAMES = ["mode", "topic", "source", "language", "style", "format",
                  "duration", "tts", "images", "quality", "subtitles", "output"]
    step = 0
    _default_out = os.path.join(os.getcwd(), "video_output")

    while step < len(STEP_NAMES):
        sname = STEP_NAMES[step]

        # ── Mode ──────────────────────────────────────────────────────────────
        if sname == "mode":
            if is_tg:
                step += 1; continue
            print(_clr(f"\n  [0] Content mode", "bold"))
            idx_r = _video_pick("Pick mode", [
                "Auto         (AI generates story from your topic)",
                "Custom script (you provide the text — TTS reads it as narration + subtitles)",
            ], config, default=1)
            if idx_r == _VP_QUIT: return True
            if idx_r == _VP_BACK: step = max(0, step - 1); continue
            if idx_r == 1:
                W["content_mode"] = "script"
                print(_clr("\n  Paste your narration text (type END on a new line when done):", "cyan"))
                lines = []
                try:
                    while True:
                        line = _ask("  ", config)
                        if line.strip().upper() == "END":
                            break
                        lines.append(line)
                except (KeyboardInterrupt, EOFError):
                    pass
                W["script_text"] = "\n".join(lines).strip()
                if not W["script_text"]:
                    _warn("  No text entered — switching to AI mode")
                    W["content_mode"] = "ai"
                else:
                    wc = len(W["script_text"].split())
                    print(_clr(f"  → Script: {wc} words", "dim"))
                    W["subtitle_mode"] = "story"
            else:
                W["content_mode"] = "ai"
            step += 1

        # ── Topic ─────────────────────────────────────────────────────────────
        elif sname == "topic":
            if is_tg or W["content_mode"] == "script":
                step += 1; continue
            cur = W["topic"] or ""
            hint = f" [{cur[:50]}...]" if cur else " (Enter for auto)"
            try:
                val = _ask(_clr(f"  Topic / idea{hint}: ", "cyan"), config).strip()
            except (KeyboardInterrupt, EOFError):
                return True
            if val.lower() in ("q", "quit"): return True
            if val.lower() in ("b", "back"):
                step = max(0, step - 1); continue
            if val:
                W["topic"] = val
            step += 1

        # ── Source folder ──────────────────────────────────────────────────────
        elif sname == "source":
            if is_tg or W["source_dir"]:
                step += 1; continue
            try:
                src_raw = _ask(_clr("  Source folder/file (Enter to skip  b=back): ", "cyan"), config).strip()
            except (KeyboardInterrupt, EOFError):
                return True
            if src_raw.lower() in ("q", "quit"): return True
            if src_raw.lower() in ("b", "back"):
                step = max(0, step - 1); continue
            if src_raw:
                src_raw = os.path.expanduser(src_raw)
                if os.path.isfile(src_raw):
                    from .source import summarise_source_for_story
                    snippet = summarise_source_for_story([src_raw], max_chars=6000)
                    if snippet:
                        t = W["topic"]
                        W["topic"] = (t + "\n\nSource context:\n" + snippet) if t else snippet
                        print(_clr(f"  Using file: {os.path.basename(src_raw)}", "dim"))
                    else:
                        _warn(f"  Could not read: {src_raw}")
                elif os.path.isdir(src_raw):
                    W["source_dir"] = src_raw
                    from .source import scan_source_dir, summarise_source_for_story
                    si = scan_source_dir(src_raw)
                    for kind, files in si.items():
                        if files:
                            print(_clr(f"    {kind}: {len(files)} file(s)", "dim"))
                    if not W["topic"] and si["text"]:
                        W["topic"] = summarise_source_for_story(si["text"])
                        print(_clr(f"  Auto-topic: {W['topic'][:80]}...", "dim"))
                else:
                    _warn(f"  Path not found: {src_raw}")
            step += 1

        # ── Language ──────────────────────────────────────────────────────────
        elif sname == "language":
            print(_clr(f"\n  [{step}] Language", "bold"))
            auto_idx = _detect_lang(W["topic"])
            auto_label = VIDEO_LANGUAGES[auto_idx][0]
            lang_options = (
                [f"Auto         (detected: {auto_label})"]
                + [row[0] for row in VIDEO_LANGUAGES]
                + ["✏️  Other (type your own)"]
            )
            idx_r = _video_pick("Pick language", lang_options, config, default=1)
            if idx_r == _VP_QUIT: return True
            if idx_r == _VP_BACK: step = max(0, step - 1); continue
            if idx_r == 0:
                W["lang_idx"] = auto_idx
            elif 1 <= idx_r <= len(VIDEO_LANGUAGES):
                W["lang_idx"] = idx_r - 1
            else:
                try:
                    lname = _ask(_clr("  Language name: ", "cyan"), config).strip()
                    wcode = _ask(_clr("  Whisper code (e.g. it, th — Enter to skip): ", "cyan"), config).strip()
                except (KeyboardInterrupt, EOFError):
                    lname, wcode = "English", ""
                W["lang_idx"] = -1
                W["lang_name"] = (lname or "English", wcode or "auto")
            step += 1

        # ── Style / Niche ──────────────────────────────────────────────────────
        elif sname == "style":
            if W["content_mode"] == "script":
                step += 1; continue
            print(_clr(f"\n  [{step}] Style / Niche", "bold"))
            print(_clr("   1.", "cyan") + "  Auto-viral (AI picks best niche)")
            for i, (k, v) in enumerate(CONTENT_NICHES.items(), 2):
                print(_clr(f"  {i:2d}.", "cyan") + f"  {v['nombre']}")
            other_n = len(CONTENT_NICHES) + 2
            print(_clr(f"  {other_n:2d}.", "cyan") + "  Other (describe your own style)")
            try:
                raw_n = _ask(_clr("  Pick style  [Enter=Auto  b=back  q=quit]: ", "cyan"), config).strip().lower()
            except (KeyboardInterrupt, EOFError):
                return True
            if raw_n in ("q", "quit"): return True
            if raw_n in ("b", "back"): step = max(0, step - 1); continue
            if not raw_n or raw_n == "1":
                W["niche_name"] = None
                print(_clr("  → Auto-viral", "dim"))
            elif raw_n.isdigit():
                n = int(raw_n)
                if 2 <= n <= len(CONTENT_NICHES) + 1:
                    W["niche_name"] = niche_keys[n - 2]
                    print(_clr(f"  → {CONTENT_NICHES[W['niche_name']]['nombre']}", "dim"))
                elif n == other_n:
                    try:
                        desc = _ask(_clr("  Describe style: ", "cyan"), config).strip()
                    except (KeyboardInterrupt, EOFError):
                        desc = ""
                    if desc:
                        t = W["topic"]
                        W["topic"] = (t + "\n\nContent style: " + desc) if t else ("Content style: " + desc)
                        print(_clr(f"  → Custom: {desc}", "dim"))
                    W["niche_name"] = None
                else:
                    W["niche_name"] = None
            elif raw_n in CONTENT_NICHES:
                W["niche_name"] = raw_n
            else:
                t = W["topic"]
                W["topic"] = (t + "\n\nContent style: " + raw_n) if t else ("Content style: " + raw_n)
                W["niche_name"] = None
            step += 1

        # ── Format ────────────────────────────────────────────────────────────
        elif sname == "format":
            print(_clr(f"\n  [{step}] Format", "bold"))
            idx_r = _video_pick("Pick format", [
                "Auto         (Landscape 16:9, YouTube standard)",
                "Landscape    16:9  (YouTube)",
                "Short        9:16  (TikTok, Reels, Shorts)",
            ], config, default=1)
            if idx_r == _VP_QUIT: return True
            if idx_r == _VP_BACK: step = max(0, step - 1); continue
            W["is_short"] = (idx_r == 2)
            step += 1

        # ── Duration ──────────────────────────────────────────────────────────
        elif sname == "duration":
            if W["content_mode"] == "script":
                step += 1; continue
            print(_clr(f"\n  [{step}] Duration", "bold"))
            dur_choices = [
                "Auto         (~2 min, recommended)",
                "~30 sec      (short clip)",
                "~1 min",
                "~2 min",
                "~3 min",
                "~5 min",
                "Custom       (type any length)",
            ]
            dur_values = [2.0, 0.5, 1.0, 2.0, 3.0, 5.0, None]
            idx_r = _video_pick("Pick duration", dur_choices, config, default=1)
            if idx_r == _VP_QUIT: return True
            if idx_r == _VP_BACK: step = max(0, step - 1); continue
            dv = dur_values[idx_r]
            if dv is None:
                try:
                    raw_d = _ask(_clr("  Minutes (e.g. 4.5): ", "cyan"), config).strip()
                    dv = float(raw_d) if raw_d else 2.0
                except (ValueError, KeyboardInterrupt, EOFError):
                    dv = 2.0
            W["duration_min"] = dv
            step += 1

        # ── TTS Voice ─────────────────────────────────────────────────────────
        elif sname == "tts":
            print(_clr(f"\n  [{step}] Voice (TTS)", "bold"))
            _has_gemini = bool(os.getenv("GEMINI_API_KEY"))
            _has_eleven = bool(os.getenv("ELEVENLABS_API_KEY"))
            li = W["lang_idx"]
            _ev = VIDEO_LANGUAGES[li][2] if (li is not None and 0 <= li < len(VIDEO_LANGUAGES)) else "en-US-GuyNeural"
            tts_options = [
                "Auto         (Gemini → ElevenLabs → Edge)",
                f"Edge TTS     (free)  voice={_ev}",
                f"Gemini TTS   {'✓' if _has_gemini else '✗ needs GEMINI_API_KEY'}",
                f"ElevenLabs   {'✓' if _has_eleven else '✗ needs ELEVENLABS_API_KEY'}",
            ]
            tts_engines = ["auto", "edge", "gemini", "elevenlabs"]
            idx_r = _video_pick("Pick voice engine", tts_options, config, default=1)
            if idx_r == _VP_QUIT: return True
            if idx_r == _VP_BACK: step = max(0, step - 1); continue
            W["tts_engine"] = tts_engines[idx_r]
            step += 1

        # ── Images ────────────────────────────────────────────────────────────
        elif sname == "images":
            print(_clr(f"\n  [{step}] Images", "bold"))
            img_options = [
                "Auto         (Gemini Web → Web Search → Placeholder)",
                "Web Search   (free stock photos, no login needed)",
                "Gemini Web   (Imagen 3, needs 1-time browser login)",
                "Placeholder  (gradient slides, always works)",
            ]
            img_engines = ["auto", "web-search", "gemini-web", "placeholder"]
            idx_r = _video_pick("Pick image source", img_options, config, default=1)
            if idx_r == _VP_QUIT: return True
            if idx_r == _VP_BACK: step = max(0, step - 1); continue
            W["image_engine"] = img_engines[idx_r]
            step += 1

        # ── Quality ───────────────────────────────────────────────────────────
        elif sname == "quality":
            print(_clr(f"\n  [{step}] Video Quality", "bold"))
            q_options = [
                "Auto         (Medium — good balance)",
                "High         (CRF 18, slow — best quality)",
                "Medium       (CRF 23, balanced)",
                "Low          (CRF 28, fast)",
                "Minimal      (CRF 32, fastest — for testing)",
            ]
            q_values = ["medium", "high", "medium", "low", "minimal"]
            idx_r = _video_pick("Pick quality", q_options, config, default=1)
            if idx_r == _VP_QUIT: return True
            if idx_r == _VP_BACK: step = max(0, step - 1); continue
            W["quality"] = q_values[idx_r]
            step += 1

        # ── Subtitles ─────────────────────────────────────────────────────────
        elif sname == "subtitles":
            print(_clr(f"\n  [{step}] Subtitles", "bold"))
            sub_options = [
                "Auto         (Whisper transcription — requires faster-whisper)",
                "Story text   (burn story script as subtitles — works for all languages)",
                "Custom text  (type or paste your own subtitle text)",
                "None         (no subtitles)",
            ]
            idx_r = _video_pick("Pick subtitle mode", sub_options, config, default=1)
            if idx_r == _VP_QUIT: return True
            if idx_r == _VP_BACK: step = max(0, step - 1); continue
            if idx_r == 0:
                W["subtitle_mode"] = "auto"
            elif idx_r == 1:
                W["subtitle_mode"] = "story"
                print(_clr("  → Will use story text as subtitles (no Whisper needed)", "dim"))
            elif idx_r == 2:
                W["subtitle_mode"] = "custom"
                print(_clr("  Paste subtitle text (type END on a new line when done):", "cyan"))
                lines = []
                try:
                    while True:
                        line = _ask("  ", config)
                        if line.strip().upper() == "END":
                            break
                        lines.append(line)
                except (KeyboardInterrupt, EOFError):
                    pass
                W["subtitle_text"] = "\n".join(lines).strip()
                if W["subtitle_text"]:
                    preview = W["subtitle_text"][:80].replace('\n', ' ')
                    print(_clr(f"  → Custom text: {preview}{'...' if len(W['subtitle_text']) > 80 else ''}", "dim"))
                else:
                    print(_clr("  → No text entered, falling back to Auto", "dim"))
                    W["subtitle_mode"] = "auto"
            else:
                W["subtitle_mode"] = "none"
                print(_clr("  → No subtitles", "dim"))
            step += 1

        # ── Output path ───────────────────────────────────────────────────────
        elif sname == "output":
            print(_clr(f"\n  [{step}] Output path", "bold"))
            print(f"  Default: {_default_out}")
            try:
                val = _ask(_clr("  Custom dir (Enter=default  b=back  q=quit): ", "cyan"), config).strip()
            except (KeyboardInterrupt, EOFError):
                return True
            if val.lower() in ("q", "quit"): return True
            if val.lower() in ("b", "back"):
                step = max(0, step - 1); continue
            W["output_dir"] = val if val else _default_out
            step += 1

    # ── Resolve language settings ──────────────────────────────────────────────
    li = W["lang_idx"]
    if li is None:
        li = _detect_lang(W["topic"])
    if li == -1:
        lname, wcode = W["lang_name"]
        subtitle_lang    = wcode
        edge_voice       = "en-US-GuyNeural"
        story_lang_instr = f"Write the story ENTIRELY in {lname}."
        _lang_display    = lname
    elif 0 <= li < len(VIDEO_LANGUAGES):
        _, subtitle_lang, edge_voice, story_lang_instr = VIDEO_LANGUAGES[li]
        _lang_display = VIDEO_LANGUAGES[li][0]
    else:
        subtitle_lang, edge_voice, story_lang_instr = "en", "en-US-GuyNeural", ""
        _lang_display = "English"

    topic        = W["topic"]
    source_dir   = W["source_dir"]
    niche_name   = W["niche_name"]
    is_short     = W["is_short"]
    duration_min = W["duration_min"]
    tts_engine   = W["tts_engine"]
    image_engine = W["image_engine"]
    quality      = W["quality"]
    output_dir   = W["output_dir"] or _default_out
    script_text  = W["script_text"] if W["content_mode"] == "script" else None

    _sub_mode = W.get("subtitle_mode", "auto")
    if _sub_mode == "none":
        subtitle_text = ""
    elif _sub_mode == "story":
        subtitle_text = "__story__"
    elif _sub_mode == "custom" and W.get("subtitle_text"):
        subtitle_text = W["subtitle_text"]
    else:
        subtitle_text = None

    # ── Summary + confirm ──────────────────────────────────────────────────────
    fmt_label = "Short 9:16" if is_short else "Landscape 16:9"
    _sub_label = {"auto": "Whisper auto", "story": "Script text", "none": "None"}.get(
        _sub_mode, f"Custom ({len(W.get('subtitle_text',''))} chars)")
    print(_clr("\n╭─ Settings Summary ──────────────────────────────────────╮", "dim"))
    if script_text:
        wc = len(script_text.split())
        print(f"  Mode:     Custom script ({wc} words)")
        print(f"  Script:   {script_text[:70].replace(chr(10),' ')}{'...' if len(script_text) > 70 else ''}")
    else:
        print(f"  Topic:    {(topic or '(auto)')[:70]}")
        print(f"  Niche:    {niche_name or 'auto-viral'}")
    print(f"  Language: {_lang_display}")
    print(f"  Format:   {fmt_label}" + ("" if script_text else f"  |  Duration: {duration_min} min"))
    print(f"  Voice:    {tts_engine}  |  Images: {image_engine}  |  Quality: {quality}")
    print(f"  Subtitles: {_sub_label}")
    if source_dir:
        print(f"  Source:   {source_dir}")
    print(f"  Output:   {output_dir}")
    print(f"  Model:    {config['model']}")
    print(_clr("╰─────────────────────────────────────────────────────────╯", "dim"))

    if not is_tg:
        try:
            go = _ask(_clr("\n  Start? [Y/n/b=redo last step]: ", "cyan"), config).strip().lower()
            if go in ("b", "back"):
                step = len(STEP_NAMES) - 1
                while step < len(STEP_NAMES):
                    sname = STEP_NAMES[step]
                    if sname == "output":
                        print(_clr(f"\n  [{step}] Output path", "bold"))
                        print(f"  Default: {_default_out}")
                        try:
                            val = _ask(_clr("  Custom dir (Enter=default  b=back): ", "cyan"), config).strip()
                        except (KeyboardInterrupt, EOFError):
                            return True
                        if val.lower() in ("b", "back"):
                            step = max(0, step - 1); continue
                        W["output_dir"] = val if val else _default_out
                        output_dir = W["output_dir"]
                    step += 1
            elif go in ("n", "no", "q", "quit"):
                return True
        except (KeyboardInterrupt, EOFError):
            return True

    # ── Run pipeline ───────────────────────────────────────────────────────────
    from .pipeline import create_video_story

    # Locate optional sounds directory relative to the versions parent folder
    _here        = os.path.dirname(os.path.abspath(__file__))   # .../little-coder/video/
    _pkg_dir     = os.path.dirname(_here)                        # .../little-coder/
    _versions_dir = os.path.dirname(_pkg_dir)                    # .../little-coder_versions/
    sounds_dir   = os.path.join(_versions_dir, "v-content-creator", "sounds")
    if not os.path.isdir(sounds_dir):
        sounds_dir = None

    result = create_video_story(
        topic            = topic,
        model            = config["model"],
        config           = config,
        script_text      = script_text,
        niche_name       = niche_name,
        duration_min     = duration_min,
        is_short         = is_short,
        tts_engine       = tts_engine,
        edge_voice       = edge_voice,
        image_engine     = image_engine,
        quality          = quality,
        subtitle_lang    = subtitle_lang if subtitle_lang != "auto" else "en",
        subtitle_text    = subtitle_text,
        sounds_dir       = sounds_dir,
        source_dir       = source_dir,
        story_lang_instr = story_lang_instr,
        output_dir       = output_dir,
    )

    if result:
        _ok(f"Video ready: {result['video_path']}  ({result['size_mb']} MB)")
        if result.get('srt_path'):
            _info(f"Subtitles:   {result['srt_path']}")
    else:
        _warn("Video generation failed. Run /video status to check dependencies.")

    return True


# ── Plugin interface ───────────────────────────────────────────────────────────
# little_coder.py discovers slash commands via this dict.
# Keys are the command names (without '/'), values carry the handler and help text.
COMMAND_DEFS: dict[str, dict] = {
    "video": {
        "func":    cmd_video,
        "help":    ("AI video factory: story→voice→images→mp4", ["status", "niches"]),
        "aliases": [],
    },
}
