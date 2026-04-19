"""
Text-to-speech backends for the video pipeline.

Priority:
  1. Gemini TTS  — if GEMINI_API_KEY is set (good quality, free tier)
  2. ElevenLabs  — if ELEVENLABS_API_KEY is set (premium)
  3. Edge TTS    — always free, no API key needed (fallback)
"""

import os
import re
import wave
import struct
import subprocess
import urllib.request
import json


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_cjk_heavy(text: str) -> bool:
    """Return True if text is predominantly CJK (Chinese/Japanese/Korean)."""
    cjk = sum(1 for c in text
              if '\u4e00' <= c <= '\u9fff'
              or '\u3040' <= c <= '\u30ff'
              or '\uac00' <= c <= '\ud7a3')
    return cjk / max(len(text), 1) > 0.15


def _split_chunks(text: str, max_words: int = 350) -> list[str]:
    """Split text into TTS-safe chunks.

    For CJK text: split on CJK sentence-ending punctuation (。！？…)
    and use character count instead of word count.
    For Latin text: split on .!? followed by whitespace.
    """
    if _is_cjk_heavy(text):
        # CJK: split on sentence-ending punctuation, measure by characters
        sentences = re.split(r'(?<=[。！？…])', text)
        # Convert max_words to approximate char limit (1 word ≈ 2 CJK chars)
        max_chars = max_words * 2
        chunks: list[str] = []
        current = ""
        for sent in sentences:
            if len(current) + len(sent) > max_chars and current:
                chunks.append(current)
                current = sent
            else:
                current += sent
        if current:
            chunks.append(current)
        return chunks or [text]

    # Latin text: original word-based splitting
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks_l: list[str] = []
    current_l: list[str] = []
    count = 0
    for sent in sentences:
        wc = len(sent.split())
        if count + wc > max_words and current_l:
            chunks_l.append(' '.join(current_l))
            current_l, count = [], 0
        current_l.append(sent)
        count += wc
    if current_l:
        chunks_l.append(' '.join(current_l))
    return chunks_l


def _crossfade_pcm(pcm_a: bytes, pcm_b: bytes, fade_ms: int = 80) -> bytes:
    """Crossfade two raw 16-bit LE mono PCM streams."""
    sample_rate = 24000
    fade_samples = int(sample_rate * fade_ms / 1000)
    min_bytes = min(len(pcm_a), len(pcm_b), fade_samples * 2)
    if min_bytes < 2:
        return pcm_a + pcm_b
    fade_samples = min_bytes // 2
    tail = struct.unpack(f'<{fade_samples}h', pcm_a[-min_bytes:])
    head = struct.unpack(f'<{fade_samples}h', pcm_b[:min_bytes])
    mixed = []
    for i in range(fade_samples):
        t = i / fade_samples
        s = int(tail[i] * (1.0 - t) + head[i] * t)
        mixed.append(max(-32768, min(32767, s)))
    return pcm_a[:-min_bytes] + struct.pack(f'<{fade_samples}h', *mixed) + pcm_b[min_bytes:]


# ── Gemini TTS ────────────────────────────────────────────────────────────────

_GEMINI_TTS_MODEL = "gemini-2.5-pro-preview-tts"
_GEMINI_TTS_URL   = f"https://generativelanguage.googleapis.com/v1beta/models/{_GEMINI_TTS_MODEL}:generateContent"


def _gemini_chunk_to_pcm(text: str, api_key: str, voice: str = "Charon") -> bytes | None:
    import base64
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    try:
        req = urllib.request.Request(
            f"{_GEMINI_TTS_URL}?key={api_key}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        b64 = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        return base64.b64decode(b64)
    except Exception as exc:
        print(f"    Gemini TTS chunk error: {exc}")
        return None


def generate_audio_gemini(text: str, output_path: str, voice: str = "Charon") -> bool:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return False
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return False

    chunks = _split_chunks(text)
    print(f"  Gemini TTS: {len(chunks)} chunk(s), voice={voice}")
    all_pcm = b""
    for i, chunk in enumerate(chunks, 1):
        print(f"  chunk {i}/{len(chunks)}...")
        pcm = _gemini_chunk_to_pcm(chunk, api_key, voice)
        if pcm:
            all_pcm = _crossfade_pcm(all_pcm, pcm) if all_pcm else pcm

    if not all_pcm:
        return False

    wav_path = output_path.replace('.mp3', '_raw.wav')
    with wave.open(wav_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(all_pcm)

    result = subprocess.run(
        [ffmpeg, "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-q:a", "2", output_path],
        capture_output=True, timeout=60
    )
    try:
        os.remove(wav_path)
    except OSError:
        pass
    return result.returncode == 0 and os.path.exists(output_path)


# ── ElevenLabs TTS ────────────────────────────────────────────────────────────

def generate_audio_elevenlabs(text: str, output_path: str) -> bool:
    api_key  = os.getenv("ELEVENLABS_API_KEY", "")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", os.getenv("ELEVEN_VOICE_ID", "qEWvRpD5bptlI1hEomR7"))
    if not api_key:
        return False

    url     = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2_5",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.3, "use_speaker_boost": True},
    }
    headers = {"Content-Type": "application/json", "xi-api-key": api_key, "Accept": "audio/mpeg"}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=300) as resp:
            audio_data = resp.read()
        if len(audio_data) > 1000:
            with open(output_path, 'wb') as f:
                f.write(audio_data)
            print(f"  ElevenLabs TTS: {len(audio_data) // 1024} KB")
            return True
        return False
    except Exception as exc:
        print(f"  ElevenLabs error: {exc}")
        return False


# ── Edge TTS (free) ───────────────────────────────────────────────────────────
# Edge TTS silently truncates long text (service-side limit ≈ 3 000–5 000 chars).
# Fix: split into safe-size chunks, synthesise each, concatenate with ffmpeg.
_EDGE_MAX_CHARS = 2000   # conservative safe limit per request


def _edge_synthesise_chunk(chunk: str, voice: str, tmp_path: str) -> bool:
    """Synthesise a single text chunk to tmp_path (MP3). Returns success."""
    import edge_tts, asyncio

    async def _run():
        communicate = edge_tts.Communicate(chunk, voice)
        await communicate.save(tmp_path)

    asyncio.run(_run())
    return os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 100


def _split_edge_chunks(text: str) -> list[str]:
    """Split text into chunks ≤ _EDGE_MAX_CHARS, breaking on sentence boundaries."""
    if len(text) <= _EDGE_MAX_CHARS:
        return [text]

    # Use the shared sentence splitter (handles CJK + Latin)
    fine = _split_chunks(text, max_words=150)   # conservative: ~300 CJK chars / 150 words

    chunks: list[str] = []
    current = ""
    for sent in fine:
        if len(current) + len(sent) > _EDGE_MAX_CHARS and current:
            chunks.append(current.strip())
            current = sent
        else:
            current += sent
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text]


def _concat_mp3_ffmpeg(part_paths: list[str], output_path: str) -> bool:
    """Concatenate MP3 files using ffmpeg concat demuxer."""
    import tempfile
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return False
    # Write concat list
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for p in part_paths:
            f.write(f"file '{p}'\n")
        list_path = f.name
    try:
        r = subprocess.run(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0",
             "-i", list_path, "-c", "copy", output_path],
            capture_output=True, timeout=120,
        )
        return r.returncode == 0 and os.path.exists(output_path)
    finally:
        try: os.unlink(list_path)
        except OSError: pass


def generate_audio_edge(text: str, output_path: str, voice: str = "en-US-GuyNeural") -> bool:
    try:
        import edge_tts  # noqa: F401  (checked for ImportError)
    except ImportError:
        print("  Edge TTS not installed. Run: pip install edge-tts")
        return False

    import tempfile

    # Auto-switch to a CJK voice when the text is predominantly CJK and the
    # selected voice is a non-CJK locale — English voices silently skip CJK chars.
    _CJK_VOICE = "zh-CN-XiaoxiaoNeural"
    if _is_cjk_heavy(text) and not voice.startswith(("zh-", "ja-", "ko-")):
        print(f"  CJK text detected — auto-switching voice: {voice} → {_CJK_VOICE}")
        voice = _CJK_VOICE

    chunks = _split_edge_chunks(text)
    print(f"  Edge TTS: {len(chunks)} chunk(s), voice={voice}")

    if len(chunks) == 1:
        # Fast path — single chunk, no temp files needed
        try:
            _edge_synthesise_chunk(chunks[0], voice, output_path)
            ok = os.path.exists(output_path) and os.path.getsize(output_path) > 100
            if ok:
                print(f"  Edge TTS: done")
            return ok
        except Exception as exc:
            print(f"  Edge TTS error: {exc}")
            return False

    # Multi-chunk path: synthesise each → ffmpeg concat
    tmp_files: list[str] = []
    try:
        for i, chunk in enumerate(chunks, 1):
            print(f"  chunk {i}/{len(chunks)} ({len(chunk)} chars)...")
            fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            tmp_files.append(tmp_path)
            try:
                if not _edge_synthesise_chunk(chunk, voice, tmp_path):
                    print(f"  chunk {i} failed — skipping")
            except Exception as exc:
                print(f"  chunk {i} error: {exc}")

        # Keep only chunks that actually produced audio
        good = [p for p in tmp_files if os.path.exists(p) and os.path.getsize(p) > 100]
        if not good:
            return False
        if len(good) == 1:
            import shutil
            shutil.copy(good[0], output_path)
            return True
        if _concat_mp3_ffmpeg(good, output_path):
            print(f"  Edge TTS: done ({len(good)} chunks merged)")
            return True
        # ffmpeg not available: just copy the first chunk (partial audio)
        import shutil
        shutil.copy(good[0], output_path)
        print("  Edge TTS: ffmpeg not found — only first chunk saved")
        return True
    except Exception as exc:
        print(f"  Edge TTS error: {exc}")
        return False
    finally:
        for p in tmp_files:
            try: os.unlink(p)
            except OSError: pass


# ── Unified entry point ───────────────────────────────────────────────────────

def generate_audio(text: str, output_path: str,
                   engine: str = "auto",
                   voice: str = "Charon",
                   edge_voice: str = "en-US-GuyNeural") -> bool:
    """
    Generate audio for story_text and save to output_path.

    engine: "auto" | "gemini" | "elevenlabs" | "edge"
    - "auto": try gemini → elevenlabs → edge in order
    """
    clean_text = re.sub(r'[\[\]*"]', '', text)

    if engine in ("gemini", "auto"):
        if generate_audio_gemini(clean_text, output_path, voice=voice):
            return True
        if engine == "gemini":
            return False

    if engine in ("elevenlabs", "auto"):
        if generate_audio_elevenlabs(clean_text, output_path):
            return True
        if engine == "elevenlabs":
            return False

    # Edge TTS is always the final fallback
    return generate_audio_edge(clean_text, output_path, voice=edge_voice)


# ── Utility ───────────────────────────────────────────────────────────────────

def _find_ffmpeg() -> str | None:
    import shutil
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        return get_ffmpeg_exe()
    except ImportError:
        return None
