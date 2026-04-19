"""Speech-to-text (STT) backends.

Backend priority (tried in order):
  1. faster-whisper  — local, offline, fastest, best for coding vocab.
                       pip install faster-whisper
  2. openai-whisper  — local, offline, original OpenAI Whisper library.
                       pip install openai-whisper
  3. OpenAI Whisper API — cloud, needs OPENAI_API_KEY.
                          pip install openai  (already in requirements)

All backends receive raw PCM (int16, 16 kHz, mono) and return a text string.
Keyterms are passed as initial_prompt to local Whisper backends so that
coding-domain vocabulary (grep, MCP, TypeScript, …) is recognised correctly.
"""

from __future__ import annotations

import io
import os
import struct
import tempfile
from pathlib import Path
from typing import List, Optional

from .recorder import SAMPLE_RATE, CHANNELS, BYTES_PER_SAMPLE

# ── Cached model handles ──────────────────────────────────────────────────

_faster_whisper_model = None
_openai_whisper_model = None

# Model size: "tiny", "base", "small", "medium", "large-v2", "large-v3"
# "base" is a good balance of speed and accuracy for coding dictation.
# Override with env var NANO_CLAUDE_WHISPER_MODEL.
DEFAULT_MODEL_SIZE = os.environ.get("NANO_CLAUDE_WHISPER_MODEL", "base")


# ── OGG/audio file → PCM conversion ──────────────────────────────────────

def _audio_file_to_pcm(audio_bytes: bytes, suffix: str = ".ogg") -> bytes:
    """Convert an audio file (OGG, MP3, etc.) to raw int16 PCM (16kHz mono) via ffmpeg."""
    import subprocess
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        f.flush()
        tmp_in = f.name
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_in, "-f", "s16le", "-ar", str(SAMPLE_RATE),
             "-ac", str(CHANNELS), "-acodec", "pcm_s16le", "-"],
            capture_output=True, timeout=30,
        )
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {r.stderr[:200]}")
        return r.stdout
    finally:
        Path(tmp_in).unlink(missing_ok=True)


# ── WAV helper ────────────────────────────────────────────────────────────

def _pcm_to_wav(pcm_bytes: bytes) -> bytes:
    """Wrap raw int16 PCM in a minimal WAV container."""
    num_samples = len(pcm_bytes) // BYTES_PER_SAMPLE
    byte_rate = SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE
    block_align = CHANNELS * BYTES_PER_SAMPLE
    data_size = len(pcm_bytes)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,          # chunk size
        1,           # PCM format
        CHANNELS,
        SAMPLE_RATE,
        byte_rate,
        block_align,
        16,          # bits per sample
        b"data",
        data_size,
    )
    return header + pcm_bytes


# ── Availability ──────────────────────────────────────────────────────────

def check_stt_availability() -> tuple[bool, str | None]:
    """Return (available, reason_if_not)."""
    try:
        import faster_whisper  # noqa: F401
        return True, None
    except ImportError:
        pass
    try:
        import whisper  # noqa: F401
        return True, None
    except ImportError:
        pass
    if os.environ.get("OPENAI_API_KEY"):
        return True, None

    return False, (
        "No STT backend available.\n"
        "Install one of:\n"
        "  pip install faster-whisper   (local, recommended)\n"
        "  pip install openai-whisper   (local, original)\n"
        "  Set OPENAI_API_KEY to use the OpenAI Whisper cloud API"
    )


def get_stt_backend_name() -> str:
    """Return a human-readable name of the backend that will be used."""
    try:
        import faster_whisper  # noqa: F401
        return f"faster-whisper ({DEFAULT_MODEL_SIZE})"
    except ImportError:
        pass
    try:
        import whisper  # noqa: F401
        return f"openai-whisper ({DEFAULT_MODEL_SIZE})"
    except ImportError:
        pass
    if os.environ.get("OPENAI_API_KEY"):
        return "OpenAI Whisper API"
    return "(none)"


# ── faster-whisper ────────────────────────────────────────────────────────

def _get_faster_whisper_model():
    global _faster_whisper_model
    if _faster_whisper_model is None:
        from faster_whisper import WhisperModel
        # Use CPU by default; set device="cuda" if GPU available.
        device = "cuda" if _has_cuda() else "cpu"
        compute = "float16" if device == "cuda" else "int8"
        _faster_whisper_model = WhisperModel(
            DEFAULT_MODEL_SIZE,
            device=device,
            compute_type=compute,
        )
    return _faster_whisper_model


def _has_cuda() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        pass
    try:
        import ctranslate2
        return "cuda" in ctranslate2.get_supported_compute_types("cuda")
    except Exception:
        return False


def _transcribe_faster_whisper(
    pcm_bytes: bytes,
    keyterms: List[str],
    language: Optional[str],
) -> str:
    import numpy as np

    model = _get_faster_whisper_model()

    # Convert int16 PCM to float32 normalised array
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    initial_prompt = _keyterms_to_prompt(keyterms)
    lang = None if not language or language == "auto" else language

    segments, _info = model.transcribe(
        audio,
        language=lang,
        initial_prompt=initial_prompt,
        vad_filter=True,          # skip silent regions
        vad_parameters=dict(
            min_silence_duration_ms=300,
        ),
    )
    return " ".join(seg.text for seg in segments).strip()


# ── openai-whisper ────────────────────────────────────────────────────────

def _get_openai_whisper_model():
    global _openai_whisper_model
    if _openai_whisper_model is None:
        import whisper
        _openai_whisper_model = whisper.load_model(DEFAULT_MODEL_SIZE)
    return _openai_whisper_model


def _transcribe_openai_whisper(
    pcm_bytes: bytes,
    keyterms: List[str],
    language: Optional[str],
) -> str:
    import numpy as np

    model = _get_openai_whisper_model()
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    initial_prompt = _keyterms_to_prompt(keyterms)
    options: dict = {"initial_prompt": initial_prompt} if initial_prompt else {}
    if language and language != "auto":
        options["language"] = language

    result = model.transcribe(audio, **options)
    return result.get("text", "").strip()


# ── OpenAI Whisper API ────────────────────────────────────────────────────

def _transcribe_openai_api(
    pcm_bytes: bytes,
    language: Optional[str],
) -> str:
    from openai import OpenAI

    client = OpenAI()  # uses OPENAI_API_KEY from env
    wav = _pcm_to_wav(pcm_bytes)

    kwargs: dict = {"model": "whisper-1", "file": ("audio.wav", io.BytesIO(wav), "audio/wav")}
    if language and language != "auto":
        kwargs["language"] = language

    transcript = client.audio.transcriptions.create(**kwargs)
    return transcript.text.strip()


# ── Keyterms → prompt ─────────────────────────────────────────────────────

def _keyterms_to_prompt(keyterms: List[str]) -> str:
    """Convert a list of keywords into a Whisper initial_prompt string.

    Whisper treats the initial_prompt as preceding context; sprinkling the
    coding vocabulary terms nudges the model to prefer these spellings.
    """
    if not keyterms:
        return ""
    # Keep it short — Whisper truncates at ~224 tokens.
    return ", ".join(keyterms[:40])


# ── Public entry point ────────────────────────────────────────────────────

def transcribe(
    pcm_bytes: bytes,
    keyterms: Optional[List[str]] = None,
    language: str = "auto",
) -> str:
    """Transcribe raw PCM audio to text.

    Args:
        pcm_bytes: Raw int16 PCM, 16 kHz, mono.
        keyterms:  Coding-domain vocabulary hints (improves accuracy).
        language:  BCP-47 language code, or 'auto' for detection.

    Returns:
        Transcribed text, or empty string if audio contains no speech.
    """
    if not pcm_bytes:
        return ""

    terms = keyterms or []
    lang = None if language == "auto" else language

    # faster-whisper (local, preferred)
    try:
        import faster_whisper  # noqa: F401
        return _transcribe_faster_whisper(pcm_bytes, terms, lang)
    except ImportError:
        pass

    # openai-whisper (local, fallback)
    try:
        import whisper  # noqa: F401
        return _transcribe_openai_whisper(pcm_bytes, terms, lang)
    except ImportError:
        pass

    # OpenAI Whisper API (cloud, last resort)
    if os.environ.get("OPENAI_API_KEY"):
        return _transcribe_openai_api(pcm_bytes, lang)

    raise RuntimeError(
        "No STT backend available.\n"
        "Install faster-whisper:  pip install faster-whisper\n"
        "Or set OPENAI_API_KEY to use the OpenAI Whisper cloud API."
    )


def transcribe_audio_file(
    audio_bytes: bytes,
    suffix: str = ".ogg",
    language: str = "auto",
) -> str:
    """Transcribe an audio file (OGG, MP3, etc.) to text.

    Converts to PCM via ffmpeg, then runs through the STT pipeline.
    Falls back to OpenAI Whisper API (which accepts OGG natively) if
    ffmpeg is not available.
    """
    # Try ffmpeg conversion → local STT
    try:
        pcm = _audio_file_to_pcm(audio_bytes, suffix)
    except (RuntimeError, FileNotFoundError):
        pcm = None

    if pcm is not None:
        try:
            return transcribe(pcm, language=language)
        except RuntimeError:
            pass  # local STT backend failed, fall through to cloud API

    # Fallback: OpenAI Whisper API accepts OGG directly
    if os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        client = OpenAI()
        kwargs: dict = {"model": "whisper-1", "file": (f"audio{suffix}", io.BytesIO(audio_bytes), "audio/ogg")}
        lang = None if language == "auto" else language
        if lang:
            kwargs["language"] = lang
        transcript = client.audio.transcriptions.create(**kwargs)
        return transcript.text.strip()

    raise RuntimeError(
        "Cannot transcribe audio file.\n"
        "Install ffmpeg for local conversion, or set OPENAI_API_KEY for cloud STT."
    )
