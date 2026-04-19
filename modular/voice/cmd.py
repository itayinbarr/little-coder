"""
Voice slash-command for little-coder.

Extracted from little_coder.py so the voice module is self-contained.
Exposes COMMAND_DEFS — the same plug-in interface used by video/cmd.py.
"""
from __future__ import annotations

import sys

# ── Minimal ANSI helpers (self-contained, no import from little_coder) ────────
_C = {
    "cyan": "\033[36m", "green": "\033[32m", "yellow": "\033[33m",
    "red":  "\033[31m", "bold":  "\033[1m",  "dim":    "\033[2m",
    "reset": "\033[0m",
}

def _clr(text: str, *keys: str) -> str:
    return "".join(_C[k] for k in keys) + str(text) + _C["reset"]

def _info(msg: str):  print(_clr(msg, "cyan"))
def _ok(msg: str):    print(_clr(msg, "green"))
def _warn(msg: str):  print(_clr(f"Warning: {msg}", "yellow"))
def _err(msg: str):   print(_clr(f"Error: {msg}", "red"), file=sys.stderr)


def _ask(prompt: str, config) -> str:
    try:
        from tools import ask_input_interactive
        return ask_input_interactive(prompt, config)
    except ImportError:
        import re as _re
        return input(_re.sub(r'(\x1b\[[0-9;]*m)', r'\001\1\002', prompt))


# Module-level language setting — persists across calls in a session.
# Stored here so it survives little_coder.py extraction.
_voice_language: str = "auto"


def cmd_voice(args: str, state, config):
    """Voice input: record → STT → auto-submit as user message.

    /voice            — record once, transcribe, submit
    /voice status     — show backend availability
    /voice lang <code> — set STT language (e.g. zh, en, ja; 'auto' to reset)
    /voice device     — list and select input microphone
    """
    global _voice_language

    subcmd = args.strip().lower().split()[0] if args.strip() else ""
    rest = args.strip()[len(subcmd):].strip()

    # ── /voice device ──────────────────────────────────────────────────────────
    if subcmd == "device":
        try:
            from modular.voice import list_input_devices
        except ImportError:
            _err("sounddevice not available. Install with: pip install sounddevice")
            return True
        try:
            devices = list_input_devices()
        except Exception as e:
            _err(f"Could not list devices: {e}")
            return True
        if not devices:
            _err("No input devices found.")
            return True
        current = config.get("_voice_device_index")
        print(_clr("  🎙  Available input devices:", "cyan", "bold"))
        for d in devices:
            marker = " ◀" if current == d["index"] else ""
            print(f"  {d['index']:3d}. {d['name']}{_clr(marker, 'green', 'bold')}")
        sel = _ask(_clr("  Select device # (Enter to cancel): ", "cyan"), config).strip()
        if sel.isdigit():
            idx = int(sel)
            valid = [d["index"] for d in devices]
            if idx in valid:
                config["_voice_device_index"] = idx
                name = next(d["name"] for d in devices if d["index"] == idx)
                _ok(f"Microphone set to: [{idx}] {name}")
            else:
                _err(f"Invalid device index: {idx}")
        return True

    # ── /voice lang <code> ─────────────────────────────────────────────────────
    if subcmd == "lang":
        if not rest:
            _info(f"Current STT language: {_voice_language}  (use '/voice lang auto' to reset)")
            return True
        _voice_language = rest.lower()
        _ok(f"STT language set to '{_voice_language}'")
        return True

    # ── /voice status ──────────────────────────────────────────────────────────
    if subcmd == "status":
        try:
            from modular.voice import (
                check_voice_deps, check_recording_availability, check_stt_availability
            )
            from modular.voice.stt import get_stt_backend_name
        except ImportError as e:
            _err(f"voice package not available: {e}")
            return True

        rec_ok, rec_reason = check_recording_availability()
        stt_ok, stt_reason = check_stt_availability()

        print(_clr("  Voice status:", "cyan", "bold"))
        if rec_ok:
            _ok("  Recording backend: available")
        else:
            _err(f"  Recording: {rec_reason}")
        if stt_ok:
            _ok(f"  STT backend:       {get_stt_backend_name()}")
        else:
            _err(f"  STT: {stt_reason}")
        dev_idx = config.get("_voice_device_index")
        if dev_idx is not None:
            try:
                from modular.voice import list_input_devices
                devs = list_input_devices()
                dev_name = next((d["name"] for d in devs if d["index"] == dev_idx), f"#{dev_idx}")
            except Exception:
                dev_name = f"#{dev_idx}"
            _info(f"  Microphone:    [{dev_idx}] {dev_name}")
        else:
            _info("  Microphone:    system default")
        _info(f"  Language: {_voice_language}")
        _info("  Env override: NANO_CLAUDE_WHISPER_MODEL (default: base)")
        return True

    # ── /voice [start] — record once and submit ────────────────────────────────
    try:
        from modular.voice import check_voice_deps, voice_input as _voice_input
    except ImportError:
        _err("voice/ package not found")
        return True

    available, reason = check_voice_deps()
    if not available:
        _err(f"Voice input not available:\n{reason}")
        return True

    _BARS = " ▁▂▃▄▅▆▇█"
    _last_bar: list[str] = [""]

    def on_energy(rms: float) -> None:
        level = min(int(rms * 8 / 0.08), 8)
        bar = _BARS[level]
        if bar != _last_bar[0]:
            _last_bar[0] = bar
            print(f"\r\033[K  🎙  {bar}  ", end="", flush=True)

    print(_clr("  🎙  Listening… (speak now, auto-stops on silence, Ctrl+C to cancel)", "cyan"))

    try:
        text = _voice_input(
            language=_voice_language,
            on_energy=on_energy,
            device_index=config.get("_voice_device_index"),
        )
    except KeyboardInterrupt:
        print()
        _info("  Voice input cancelled.")
        return True
    except Exception as e:
        print()
        _err(f"Voice input error: {e}")
        return True

    print()

    if not text:
        _info("  (nothing transcribed — no speech detected)")
        return True

    _ok(f'  Transcribed: \u201c{text}\u201d')
    print()

    # Pass transcribed text back to REPL via sentinel (same mechanism as before)
    return ("__voice__", text)


# ══════════════════════════════════════════════════════════════════════════════
# /tts — AI-powered text-to-speech generation wizard
# ══════════════════════════════════════════════════════════════════════════════

def _text_length_display(text: str) -> str:
    """Smart length display: char count for CJK-heavy text, word count otherwise."""
    if not text:
        return "0 chars"
    cjk = sum(1 for c in text
               if '\u4e00' <= c <= '\u9fff'   # CJK unified
               or '\u3040' <= c <= '\u30ff'   # Hiragana / Katakana
               or '\uac00' <= c <= '\ud7a3')  # Hangul
    ratio = cjk / max(len(text), 1)
    if ratio > 0.15:
        return f"{len(text)} 字符"
    words = len(text.split())
    return f"{words} words"


def cmd_tts(args: str, _state, config) -> bool:
    """AI-powered TTS generator — write text in any style, synthesize to audio.

    Usage:
      /tts [topic]        Launch interactive wizard
      /tts status         Show dependency status
    """
    import os as _os
    from modular.voice.tts_gen import (
        VOICE_STYLES, EDGE_VOICES, GEMINI_VOICES,
        check_tts_deps, run_tts_pipeline,
    )

    sub = args.strip().split()[0].lower() if args.strip() else ""

    # ── /tts status ───────────────────────────────────────────────────────────
    if sub == "status":
        deps = check_tts_deps()
        print(_clr("\n  TTS Dependencies\n", "bold"))
        rows = [
            ("ffmpeg",            deps.get("ffmpeg"),      "Audio encoding"),
            ("edge-tts",          deps.get("edge_tts"),    "Free TTS (fallback)  pip install edge-tts"),
            ("GEMINI_API_KEY",    deps.get("gemini"),      "Gemini TTS (high quality, free tier)"),
            ("ELEVENLABS_API_KEY",deps.get("elevenlabs"),  "ElevenLabs TTS (premium)"),
        ]
        for name, flag, note in rows:
            mark = _clr("✓", "green") if flag else _clr("✗", "red")
            print(f"  {mark}  {name:<22} {note}")
        print()
        return True

    topic_from_args = " ".join(
        t for t in args.strip().split() if t.lower() != "status"
    ).strip()

    # ══════════════════════════════════════════════════════════════════════════
    # WIZARD — Enter = Auto on every step, b = back, q = quit
    # ══════════════════════════════════════════════════════════════════════════
    print(_clr("\n╭─ 🎙 TTS Content Factory ────────────────────────────────╮", "bold"))
    print(_clr("│  Enter=Auto on every step  ·  b=back  ·  q=quit         │", "dim"))
    print(_clr("╰─────────────────────────────────────────────────────────╯\n", "bold"))

    _VP_BACK, _VP_QUIT = -1, -2

    def _pick(prompt: str, options: list[str], default: int = 1) -> int:
        """Show numbered list. Returns 0-based index, _VP_BACK or _VP_QUIT."""
        for i, opt in enumerate(options, 1):
            print(f"{_clr(f'  {i:>2}.', 'cyan')} {opt}")
        print(_clr(f"  [Enter={default}  b=back  q=quit]", "dim"))
        try:
            raw = _ask(_clr(f"  {prompt}: ", "cyan"), config).strip().lower()
        except (KeyboardInterrupt, EOFError):
            return _VP_QUIT
        if raw in ("b", "back"):  return _VP_BACK
        if raw in ("q", "quit"):  return _VP_QUIT
        if not raw:               return default - 1
        if raw.isdigit():
            n = int(raw) - 1
            if 0 <= n < len(options): return n
        return default - 1

    style_keys = list(VOICE_STYLES.keys())

    # Defaults — Auto everywhere
    W: dict = {
        "mode":         "ai",        # "ai" | "text"
        "topic":        topic_from_args,
        "custom_text":  "",
        "style_key":    "narrator",  # default when Auto chosen
        "custom_style": "",
        "duration_sec": 60,
        "engine":       "auto",
        "gemini_voice": "Charon",
        "edge_voice":   "en-US-GuyNeural",
        "output_dir":   _os.path.join(_os.getcwd(), "tts_output"),
    }

    STEPS = ["mode", "topic", "style", "duration", "engine", "voice", "output"]
    step = 0

    while step < len(STEPS):
        sname = STEPS[step]

        # ── [0] Mode ──────────────────────────────────────────────────────────
        if sname == "mode":
            print(_clr("\n  [0] Content mode", "bold"))
            idx = _pick("Pick mode", [
                "Auto         (AI generates script from your topic)",
                "Custom text  (paste your own script → TTS reads every word)",
            ], default=1)
            if idx == _VP_QUIT: return True
            if idx == _VP_BACK: step = max(0, step - 1); continue

            if idx == 1:   # Custom text
                W["mode"] = "text"
                print(_clr("\n  Paste your script (type END on a new line when done):", "cyan"))
                lines = []
                try:
                    while True:
                        line = _ask("  ", config)
                        if line.strip().upper() == "END":
                            break
                        lines.append(line)
                except (KeyboardInterrupt, EOFError):
                    pass
                W["custom_text"] = "\n".join(lines).strip()
                if not W["custom_text"]:
                    _warn("No text entered — switching to AI mode")
                    W["mode"] = "ai"
                else:
                    print(_clr(f"  → Script: {_text_length_display(W['custom_text'])}", "dim"))
            else:          # Auto / AI
                W["mode"] = "ai"
            step += 1

        # ── Topic (AI mode only) ───────────────────────────────────────────────
        elif sname == "topic":
            if W["mode"] == "text":
                step += 1; continue
            cur = W["topic"] or ""
            hint = f" [{cur[:50]}]" if cur else " (Enter for auto)"
            try:
                val = _ask(_clr(f"  Topic / subject{hint}: ", "cyan"), config).strip()
            except (KeyboardInterrupt, EOFError):
                return True
            if val.lower() in ("q", "quit"): return True
            if val.lower() in ("b", "back"):
                step = max(0, step - 1); continue
            if val: W["topic"] = val
            step += 1

        # ── [1] Voice style ────────────────────────────────────────────────────
        elif sname == "style":
            print(_clr(f"\n  [1] Voice style", "bold"))
            # Auto = "narrator" (most universal), shown as first option
            style_opts = [
                "Auto         (Narrator — calm, clear, works for all content)",
            ] + [VOICE_STYLES[k]["nombre"] for k in style_keys if k != "custom"] + [
                VOICE_STYLES["custom"]["nombre"],
            ]
            # Map option index → style key
            # idx 0 → "narrator" (Auto)
            # idx 1..N → style_keys excluding "custom"
            # idx N+1 → "custom"
            _non_custom = [k for k in style_keys if k != "custom"]
            _style_map  = ["narrator"] + _non_custom + ["custom"]

            idx = _pick("Pick style", style_opts, default=1)
            if idx == _VP_QUIT: return True
            if idx == _VP_BACK: step = max(0, step - 1); continue

            W["style_key"] = _style_map[idx]
            if W["style_key"] == "custom":
                try:
                    desc = _ask(_clr("  Describe the voice style: ", "cyan"), config).strip()
                except (KeyboardInterrupt, EOFError):
                    desc = ""
                W["custom_style"] = desc or "calm and clear"
                print(_clr(f"  → Custom: {W['custom_style']}", "dim"))
            else:
                W["gemini_voice"] = VOICE_STYLES[W["style_key"]]["gemini_voice"]
                W["edge_voice"]   = VOICE_STYLES[W["style_key"]]["edge_voice"]
                label = "Auto → Narrator" if idx == 0 else VOICE_STYLES[W["style_key"]]["nombre"]
                print(_clr(f"  → {label}", "dim"))
            step += 1

        # ── [2] Duration (AI mode only) ────────────────────────────────────────
        elif sname == "duration":
            if W["mode"] == "text":
                step += 1; continue
            print(_clr(f"\n  [2] Duration", "bold"))
            dur_opts = [
                "Auto         (~1 min, recommended)",
                "~30 sec      (short clip)",
                "~1 min",
                "~2 min",
                "~3 min",
                "~5 min",
                "Custom       (type seconds)",
            ]
            dur_vals = [60, 30, 60, 120, 180, 300, None]
            idx = _pick("Pick duration", dur_opts, default=1)
            if idx == _VP_QUIT: return True
            if idx == _VP_BACK: step = max(0, step - 1); continue
            dv = dur_vals[idx]
            if dv is None:
                try:
                    raw = _ask(_clr("  Seconds (e.g. 90): ", "cyan"), config).strip()
                    dv = int(raw) if raw.isdigit() else 60
                except (ValueError, KeyboardInterrupt, EOFError):
                    dv = 60
            W["duration_sec"] = dv
            step += 1

        # ── [3] Engine ────────────────────────────────────────────────────────
        elif sname == "engine":
            print(_clr(f"\n  [3] TTS Engine", "bold"))
            _has_gem = bool(_os.getenv("GEMINI_API_KEY"))
            _has_el  = bool(_os.getenv("ELEVENLABS_API_KEY"))
            eng_opts = [
                "Auto         (Gemini → ElevenLabs → Edge, best available)",
                f"Edge TTS     (free, always works)",
                f"Gemini TTS   {'✓' if _has_gem else '✗ needs GEMINI_API_KEY'}",
                f"ElevenLabs   {'✓' if _has_el  else '✗ needs ELEVENLABS_API_KEY'}",
            ]
            engines = ["auto", "edge", "gemini", "elevenlabs"]
            idx = _pick("Pick engine", eng_opts, default=1)
            if idx == _VP_QUIT: return True
            if idx == _VP_BACK: step = max(0, step - 1); continue
            W["engine"] = engines[idx]
            step += 1

        # ── [4] Voice ─────────────────────────────────────────────────────────
        elif sname == "voice":
            print(_clr(f"\n  [4] Voice", "bold"))

            # Gemini voice (used when engine = gemini or auto)
            if W["engine"] in ("gemini", "auto"):
                preset_gem = W["gemini_voice"]
                gem_opts = [
                    f"Auto         (style preset: {preset_gem})",
                ] + [label for label, _ in GEMINI_VOICES]
                idx = _pick("Gemini voice", gem_opts, default=1)
                if idx == _VP_QUIT: return True
                if idx == _VP_BACK: step = max(0, step - 1); continue
                if idx > 0:
                    W["gemini_voice"] = GEMINI_VOICES[idx - 1][1]
                # idx == 0 → keep preset default
                print(_clr(f"  → Gemini: {W['gemini_voice']}", "dim"))

            # Edge voice (used when engine = edge, or as fallback in auto)
            preset_edge = W["edge_voice"]
            edge_opts = [
                f"Auto         (style preset: {preset_edge})",
            ] + [label for label, _ in EDGE_VOICES]
            idx = _pick("Edge voice (fallback)", edge_opts, default=1)
            if idx == _VP_QUIT: return True
            if idx == _VP_BACK: step = max(0, step - 1); continue
            if idx > 0:
                W["edge_voice"] = EDGE_VOICES[idx - 1][1]
            print(_clr(f"  → Edge:   {W['edge_voice']}", "dim"))
            step += 1

        # ── [5] Output dir ────────────────────────────────────────────────────
        elif sname == "output":
            print(_clr(f"\n  [5] Output folder", "bold"))
            print(f"  Default: {W['output_dir']}")
            try:
                val = _ask(
                    _clr("  Custom dir (Enter=default  b=back  q=quit): ", "cyan"),
                    config,
                ).strip()
            except (KeyboardInterrupt, EOFError):
                return True
            if val.lower() in ("q", "quit"): return True
            if val.lower() in ("b", "back"):
                step = max(0, step - 1); continue
            if val: W["output_dir"] = _os.path.expanduser(val)
            step += 1

    # ── Summary + confirm ─────────────────────────────────────────────────────
    style_label = (
        f"Custom ({W['custom_style'][:40]})" if W["style_key"] == "custom"
        else VOICE_STYLES[W["style_key"]]["nombre"]
    )
    print(_clr("\n╭─ Settings Summary ──────────────────────────────────────╮", "dim"))
    if W["mode"] == "text":
        print(f"  Mode:     Custom text  ({_text_length_display(W['custom_text'])})")
    else:
        print(f"  Mode:     AI generate")
        print(f"  Topic:    {(W['topic'] or '(auto)')[:60]}")
        print(f"  Duration: {W['duration_sec']}s (~{W['duration_sec']//60}m{W['duration_sec']%60:02d}s)")
    print(f"  Style:    {style_label}")
    print(f"  Engine:   {W['engine']}  |  Gemini: {W['gemini_voice']}  |  Edge: {W['edge_voice']}")
    print(f"  Output:   {W['output_dir']}")
    print(_clr("╰─────────────────────────────────────────────────────────╯", "dim"))

    try:
        go = _ask(_clr("\n  Start? [Y/n]: ", "cyan"), config).strip().lower()
        if go in ("n", "no", "q", "quit"): return True
    except (KeyboardInterrupt, EOFError):
        return True

    # ── Run pipeline ──────────────────────────────────────────────────────────
    result = run_tts_pipeline(
        topic              = W["topic"],
        style_key          = W["style_key"],
        duration_sec       = W["duration_sec"],
        engine             = W["engine"],
        gemini_voice       = W["gemini_voice"],
        edge_voice         = W["edge_voice"],
        output_dir         = W["output_dir"],
        model              = config["model"],
        config             = config,
        custom_text        = W["custom_text"] if W["mode"] == "text" else None,
        custom_style_prompt= W["custom_style"],
    )

    if result:
        _ok(f"Audio ready: {result['audio_path']}  ({result['size_kb']} KB)")
        _info(f"Script:      {result['script_path']}")
    else:
        _warn("TTS generation failed. Run /tts status to check dependencies.")

    return True


# ── Plugin interface ───────────────────────────────────────────────────────────
COMMAND_DEFS: dict[str, dict] = {
    "voice": {
        "func":    cmd_voice,
        "help":    ("Voice input (record → STT)", ["lang", "status", "device"]),
        "aliases": [],
    },
    "tts": {
        "func":    cmd_tts,
        "help":    ("AI voice generator: text → any style → audio file", ["status"]),
        "aliases": [],
    },
}
