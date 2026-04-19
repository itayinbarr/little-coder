"""
Subtitle generation using faster-whisper (local, offline),
or from plain text with proportional timing.
Falls back gracefully if not installed.
"""

import re as _re

_whisper_model = None  # cached model instance


def _fmt_time(seconds: float) -> str:
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _split_subtitle_chunks(text: str,
                            max_words: int = 8,
                            max_cjk_chars: int = 18) -> list[str]:
    """
    Split text into natural subtitle-sized chunks.
    Handles Latin (word-based) and CJK/no-space scripts (character-based).
    """
    # Detect CJK / no-space script proportion
    cjk = sum(1 for c in text if (
        '\u4e00' <= c <= '\u9fff' or   # CJK Unified
        '\u3040' <= c <= '\u30ff' or   # Hiragana / Katakana
        '\uac00' <= c <= '\ud7af'       # Hangul
    ))
    is_cjk = cjk > len(text) * 0.25

    chunks: list[str] = []

    if is_cjk:
        # Split on sentence-ending CJK punctuation first
        sents = _re.split(r'(?<=[。！？…\n])', text.strip())
        for sent in sents:
            sent = sent.strip()
            if not sent:
                continue
            if len(sent) <= max_cjk_chars:
                chunks.append(sent)
            else:
                # Secondary split on phrase punctuation
                parts = _re.split(r'(?<=[，、；,;])', sent)
                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                    # Final hard split by character count
                    for i in range(0, len(part), max_cjk_chars):
                        piece = part[i:i + max_cjk_chars].strip()
                        if piece:
                            chunks.append(piece)
    else:
        # Split on sentence-ending punctuation, preserving it
        sents = _re.split(r'(?<=[.!?\n])\s+', text.strip())
        for sent in sents:
            sent = sent.strip()
            if not sent:
                continue
            words = sent.split()
            # Break long sentences into word groups
            for i in range(0, len(words), max_words):
                piece = ' '.join(words[i:i + max_words]).strip()
                if piece:
                    chunks.append(piece)

    # Filter out empty or punctuation-only fragments
    _punct_only = _re.compile(r'^[\s。！？，、；,.!? …\u2026\u3002]+$')
    chunks = [c for c in chunks if c.strip() and not _punct_only.match(c)]

    # Merge orphan fragments (< 2 words Latin / < 4 chars CJK) into previous chunk
    if len(chunks) < 2:
        return chunks
    merged: list[str] = [chunks[0]]
    for c in chunks[1:]:
        too_short = len(c) < 4 if is_cjk else len(c.split()) < 2
        if too_short and merged:
            merged[-1] = merged[-1] + (' ' if not is_cjk else '') + c
        else:
            merged.append(c)
    return merged


def text_to_srt(text: str, audio_path: str, srt_path: str) -> bool:
    """
    Convert plain text to a timed SRT file.
    Splits text into subtitle chunks and distributes timing proportionally
    across the audio duration (no Whisper needed).
    Returns True on success.
    """
    chunks = _split_subtitle_chunks(text)
    if not chunks:
        print("  text_to_srt: no chunks generated")
        return False

    # Get audio duration
    duration = 0.0
    try:
        from .assembly import _audio_duration
        duration = _audio_duration(audio_path)
    except Exception:
        pass
    if duration <= 0:
        duration = max(10.0, len(chunks) * 3.0)

    # Proportional timing by character count
    char_counts = [max(1, len(c)) for c in chunks]
    total_chars = sum(char_counts)

    try:
        with open(srt_path, 'w', encoding='utf-8') as f:
            elapsed = 0.0
            for i, (chunk, chars) in enumerate(zip(chunks, char_counts), 1):
                chunk_dur = max(0.8, duration * chars / total_chars)
                start = elapsed
                end   = min(elapsed + chunk_dur, duration - 0.05)
                if start >= duration:
                    break
                f.write(f"{i}\n{_fmt_time(start)} --> {_fmt_time(end)}\n{chunk}\n\n")
                elapsed = end

        print(f"  Text subtitles: {len(chunks)} entries → {srt_path}")
        return True
    except Exception as exc:
        print(f"  text_to_srt error: {exc}")
        return False


def generate_subtitles(audio_path: str, srt_path: str, language: str = "en") -> bool:
    """
    Transcribe audio_path and write an SRT file to srt_path.
    Returns True on success, False if faster-whisper is unavailable.
    """
    global _whisper_model
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("  faster-whisper not installed — subtitles skipped. (pip install faster-whisper)")
        return False

    try:
        if _whisper_model is None:
            print("  Loading Whisper model (first run downloads ~150 MB)...")
            import os
            model_size = os.getenv("NANO_CLAUDE_WHISPER_MODEL", "base")
            # Use CPU if CUDA not available
            try:
                import torch
                device      = "cuda" if torch.cuda.is_available() else "cpu"
                compute     = "float16" if device == "cuda" else "int8"
            except ImportError:
                device, compute = "cpu", "int8"
            _whisper_model = WhisperModel(model_size, device=device, compute_type=compute)

        print(f"  Transcribing audio (lang={language})...")
        segments, _ = _whisper_model.transcribe(audio_path, language=language, beam_size=5)

        with open(srt_path, 'w', encoding='utf-8') as f:
            for i, seg in enumerate(segments, 1):
                f.write(f"{i}\n{_fmt_time(seg.start)} --> {_fmt_time(seg.end)}\n{seg.text.strip()}\n\n")

        print(f"  Subtitles saved: {srt_path}")
        return True
    except Exception as exc:
        print(f"  Subtitle generation error: {exc}")
        return False
