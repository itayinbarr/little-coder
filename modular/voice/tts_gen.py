"""
modular/voice/tts_gen.py
------------------------
AI-powered TTS generation pipeline for the voice module.

Flow:
  topic / text  →  [AI writing]  →  synthesis  →  audio file

Backends (reused from modular/video/tts.py):
  Gemini TTS → ElevenLabs → Edge TTS (always-free fallback)

Voice style presets guide the LLM to produce text with the right
register, rhythm, and sentence length for the chosen vocal style.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path


# ── Voice style presets ───────────────────────────────────────────────────────

VOICE_STYLES: dict[str, dict] = {
    "narrator": {
        "nombre":   "Narrator — calm, authoritative",
        "prompt":   (
            "Write an engaging narration in a calm, clear, authoritative voice. "
            "Use short-to-medium sentences. Vary sentence length for rhythm. "
            "No stage directions, no sound effects cues. Plain prose only."
        ),
        "edge_voice": "en-US-GuyNeural",
        "gemini_voice": "Charon",
    },
    "newsreader": {
        "nombre":   "News anchor — professional, neutral",
        "prompt":   (
            "Write a professional news broadcast script. Use the inverted pyramid: "
            "most important fact first. Sentences must be short (under 20 words). "
            "Formal tone, no contractions. No editorial opinion."
        ),
        "edge_voice": "en-US-AriaNeural",
        "gemini_voice": "Aoede",
    },
    "storyteller": {
        "nombre":   "Storyteller — dramatic, immersive",
        "prompt":   (
            "Write an immersive, dramatic story excerpt meant to be read aloud. "
            "Build tension with vivid sensory detail. Mix long evocative sentences "
            "with punchy short ones. End on a cliffhanger or emotional beat."
        ),
        "edge_voice": "en-US-DavisNeural",
        "gemini_voice": "Fenrir",
    },
    "asmr": {
        "nombre":   "ASMR — soft, intimate, relaxing",
        "prompt":   (
            "Write a calming, softly spoken ASMR script. Use second-person ('you'). "
            "Speak slowly — lots of pauses implied by ellipses. Describe gentle, "
            "peaceful imagery: nature, warmth, quietness. Very short sentences."
        ),
        "edge_voice": "en-US-JennyNeural",
        "gemini_voice": "Aoede",
    },
    "motivational": {
        "nombre":   "Motivational — energetic, inspiring",
        "prompt":   (
            "Write a powerful motivational speech. Use second-person address. "
            "Build energy progressively. Short, punchy sentences. Rhetorical "
            "questions. End with a strong call to action."
        ),
        "edge_voice": "en-US-TonyNeural",
        "gemini_voice": "Puck",
    },
    "documentary": {
        "nombre":   "Documentary — informative, thoughtful",
        "prompt":   (
            "Write a thoughtful documentary narration. Balance facts with human "
            "interest. Use a warm but measured tone. Each paragraph covers one idea. "
            "Cite context without dates/numbers that age badly."
        ),
        "edge_voice": "en-GB-RyanNeural",
        "gemini_voice": "Charon",
    },
    "children": {
        "nombre":   "Children's story — warm, playful",
        "prompt":   (
            "Write a children's story segment meant to be read aloud to kids aged 4-8. "
            "Simple vocabulary. Lots of rhythm and repetition. Warm, cheerful tone. "
            "Include some gentle onomatopoeia or fun sounds to say aloud."
        ),
        "edge_voice": "en-US-AnaNeural",
        "gemini_voice": "Kore",
    },
    "podcast": {
        "nombre":   "Podcast host — conversational, casual",
        "prompt":   (
            "Write a podcast segment in a conversational, casual tone. "
            "Use contractions and natural speech patterns. Occasional rhetorical "
            "asides ('right?', 'you know what I mean'). Medium-length sentences."
        ),
        "edge_voice": "en-US-GuyNeural",
        "gemini_voice": "Puck",
    },
    "meditation": {
        "nombre":   "Meditation guide — slow, peaceful",
        "prompt":   (
            "Write a guided meditation script. Second person, present tense. "
            "Very slow implied pacing — use ellipses for pauses. Breathing cues. "
            "Peaceful imagery. End with gentle return to awareness."
        ),
        "edge_voice": "en-US-JennyNeural",
        "gemini_voice": "Aoede",
    },
    "custom": {
        "nombre":   "Custom — describe your own style",
        "prompt":   "",            # filled in by wizard
        "edge_voice": "en-US-GuyNeural",
        "gemini_voice": "Charon",
    },
}


# ── Edge TTS voice catalogue ──────────────────────────────────────────────────

EDGE_VOICES: list[tuple[str, str]] = [
    # (display_label,            voice_name)
    ("Guy (EN-US, male)",        "en-US-GuyNeural"),
    ("Jenny (EN-US, female)",    "en-US-JennyNeural"),
    ("Aria (EN-US, female)",     "en-US-AriaNeural"),
    ("Davis (EN-US, male)",      "en-US-DavisNeural"),
    ("Tony (EN-US, male)",       "en-US-TonyNeural"),
    ("Ana (EN-US child, F)",     "en-US-AnaNeural"),
    ("Ryan (EN-GB, male)",       "en-GB-RyanNeural"),
    ("Sonia (EN-GB, female)",    "en-GB-SoniaNeural"),
    ("William (EN-AU, male)",    "en-AU-WilliamNeural"),
    ("Natasha (EN-AU, female)",  "en-AU-NatashaNeural"),
    ("Yunxi (ZH-CN, male)",      "zh-CN-YunxiNeural"),
    ("Xiaoxiao (ZH-CN, female)", "zh-CN-XiaoxiaoNeural"),
    ("Keita (JA, male)",         "ja-JP-KeitaNeural"),
    ("Nanami (JA, female)",      "ja-JP-NanamiNeural"),
    ("Alvaro (ES, male)",        "es-ES-AlvaroNeural"),
    ("Henri (FR, male)",         "fr-FR-HenriNeural"),
    ("Conrad (DE, male)",        "de-DE-ConradNeural"),
    ("Dmitry (RU, male)",        "ru-RU-DmitryNeural"),
    ("Antonio (PT-BR, male)",    "pt-BR-AntonioNeural"),
]

GEMINI_VOICES: list[tuple[str, str]] = [
    ("Charon (calm, deep)",    "Charon"),
    ("Aoede (soft, female)",   "Aoede"),
    ("Fenrir (dramatic male)", "Fenrir"),
    ("Puck (energetic male)",  "Puck"),
    ("Kore (warm female)",     "Kore"),
    ("Orbit (neutral)",        "Orbit"),
]


# ── AI text generation ────────────────────────────────────────────────────────

def generate_tts_text(
    topic: str,
    style_key: str,
    duration_sec: int,
    model: str,
    config: dict,
    custom_style_prompt: str = "",
) -> str:
    """
    Use the active LLM to write narration text for TTS.

    Returns the generated text string.
    """
    from providers import stream

    style = VOICE_STYLES.get(style_key, VOICE_STYLES["narrator"])
    style_instr = custom_style_prompt if style_key == "custom" else style["prompt"]

    # Approximate word count: typical narrator reads ~130 words/min
    target_words = max(30, int(duration_sec / 60 * 130))

    system = (
        "You are a professional scriptwriter specialising in audio content. "
        "Write ONLY the spoken text — no stage directions, no speaker labels, "
        "no markdown, no brackets, no sound cues. Plain prose ready to be read aloud."
    )
    user = (
        f"Write narration about the following topic for a {duration_sec}-second audio clip "
        f"(approximately {target_words} words).\n\n"
        f"Topic: {topic}\n\n"
        f"Style instructions: {style_instr}"
    )

    messages = [{"role": "user", "content": user}]
    collected = []
    print("  Generating script", end="", flush=True)
    for chunk in stream(messages, model=model, config=config, system=system, max_tokens=2048):
        if hasattr(chunk, "text"):
            collected.append(chunk.text)
            if len(collected) % 20 == 0:
                print(".", end="", flush=True)
    print()
    return "".join(collected).strip()


# ── Core pipeline ─────────────────────────────────────────────────────────────

def create_tts_audio(
    text: str,
    output_path: str,
    engine: str = "auto",
    gemini_voice: str = "Charon",
    edge_voice: str = "en-US-GuyNeural",
) -> bool:
    """
    Synthesize text to audio using the best available backend.

    Returns True on success.
    """
    from modular.video.tts import generate_audio
    return generate_audio(
        text,
        output_path,
        engine=engine,
        voice=gemini_voice,
        edge_voice=edge_voice,
    )


def check_tts_deps() -> dict:
    """Return availability dict for TTS dependencies."""
    import shutil
    deps: dict = {}
    deps["ffmpeg"] = bool(shutil.which("ffmpeg"))
    try:
        import edge_tts  # noqa: F401
        deps["edge_tts"] = True
    except ImportError:
        deps["edge_tts"] = False
    deps["gemini"] = bool(os.getenv("GEMINI_API_KEY"))
    deps["elevenlabs"] = bool(os.getenv("ELEVENLABS_API_KEY"))
    return deps


def run_tts_pipeline(
    topic: str,
    style_key: str,
    duration_sec: int,
    engine: str,
    gemini_voice: str,
    edge_voice: str,
    output_dir: str,
    model: str,
    config: dict,
    custom_text: str | None = None,
    custom_style_prompt: str = "",
) -> dict | None:
    """
    Full TTS pipeline: optionally generate text, then synthesize.

    Returns result dict or None on failure.
    """
    os.makedirs(output_dir, exist_ok=True)
    ts = int(time.time())

    # ── Step 1: text ─────────────────────────────────────────────────────────
    if custom_text:
        text = custom_text
        print(f"  Using provided text ({len(text.split())} words)")
    else:
        print(f"\n[1/2] Generating script ({style_key}, ~{duration_sec}s)...")
        text = generate_tts_text(topic, style_key, duration_sec, model, config, custom_style_prompt)
        if not text:
            print("  Script generation failed.")
            return None
        print(f"  Script ready: {len(text.split())} words")

    # ── Step 2: synthesis ─────────────────────────────────────────────────────
    print(f"\n[2/2] Synthesizing audio ({engine})...")
    out_path = os.path.join(output_dir, f"tts_{ts}.mp3")
    ok = create_tts_audio(text, out_path, engine=engine,
                           gemini_voice=gemini_voice, edge_voice=edge_voice)
    if not ok or not os.path.exists(out_path):
        print("  Audio synthesis failed.")
        return None

    size_kb = os.path.getsize(out_path) // 1024
    # Save a companion .txt with the script
    txt_path = out_path.replace(".mp3", "_script.txt")
    Path(txt_path).write_text(text, encoding="utf-8")

    return {
        "audio_path": out_path,
        "script_path": txt_path,
        "text": text,
        "style": style_key,
        "engine": engine,
        "size_kb": size_kb,
    }
