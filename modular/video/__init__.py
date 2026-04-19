"""
Video content factory for little-coder.
Idea → AI Story → AI Voice → AI Images → Subtitles → Final Video

Zero-cost path: Edge TTS (free) + Gemini Web images (Playwright, free).
Paid path: Gemini TTS / ElevenLabs + SDXL local GPU.
"""

import shutil


def check_video_deps() -> dict:
    """Return a dict of which video pipeline dependencies are available."""
    deps: dict = {}

    # ── System tools ──────────────────────────────────────────────────────────
    deps["ffmpeg"]        = bool(shutil.which("ffmpeg"))
    deps["ffprobe"]       = bool(shutil.which("ffprobe"))

    # ── TTS backends ─────────────────────────────────────────────────────────
    try:
        import edge_tts  # noqa: F401
        deps["edge_tts"] = True
    except ImportError:
        deps["edge_tts"] = False

    # ── Subtitle generation ───────────────────────────────────────────────────
    try:
        import faster_whisper  # noqa: F401
        deps["faster_whisper"] = True
    except ImportError:
        deps["faster_whisper"] = False

    # ── Image generation ─────────────────────────────────────────────────────
    try:
        import playwright  # noqa: F401
        deps["playwright"] = True
    except ImportError:
        deps["playwright"] = False

    try:
        from PIL import Image  # noqa: F401
        deps["pillow"] = True
    except ImportError:
        deps["pillow"] = False

    return deps
