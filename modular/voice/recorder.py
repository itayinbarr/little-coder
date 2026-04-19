"""Audio capture for voice input.

Backend priority (tried in order):
  1. sounddevice   — cross-platform, pure-Python wrapper around PortAudio.
                     Best option: works on macOS, Linux, Windows.
                     pip install sounddevice
  2. arecord       — Linux ALSA utility.  No pip install needed.
  3. sox rec       — SoX command-line recorder.  Supports silence detection.
                     sudo apt install sox  /  brew install sox

All backends capture raw PCM: 16 kHz, 16-bit signed little-endian, mono.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import threading
from pathlib import Path

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
BYTES_PER_SAMPLE = 2  # int16

# Silence detection parameters
SILENCE_THRESHOLD_RMS = 0.012   # fraction of int16 max (0..1)
SILENCE_DURATION_SECS = 1.8     # stop after this many seconds of silence
CHUNK_SECS = 0.08               # 80 ms chunks for RMS poll


def _has_cmd(cmd: str) -> bool:
    return shutil.which(cmd) is not None


# ── Availability ──────────────────────────────────────────────────────────

def check_recording_availability() -> tuple[bool, str | None]:
    """Return (available, reason_if_not)."""
    # sounddevice (ImportError = not installed; OSError = PortAudio library missing)
    try:
        import sounddevice  # noqa: F401
        return True, None
    except (ImportError, OSError):
        pass

    # arecord
    if _has_cmd("arecord"):
        return True, None

    # sox rec
    if _has_cmd("rec"):
        return True, None

    return False, (
        "No audio recording backend found.\n"
        "Install one of:\n"
        "  pip install sounddevice   (recommended, cross-platform)\n"
        "  sudo apt install alsa-utils  (Linux — provides arecord)\n"
        "  sudo apt install sox  /  brew install sox  (SoX rec)"
    )


# ── sounddevice backend ───────────────────────────────────────────────────

def list_input_devices() -> list[dict]:
    """Return a list of available input devices with index and name."""
    import sounddevice as sd
    devices = sd.query_devices()
    result = []
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0:
            result.append({"index": i, "name": d["name"]})
    return result


def _record_sounddevice(
    max_seconds: int = 30,
    on_energy: "callable | None" = None,
    device_index: "int | None" = None,
) -> bytes:
    import sounddevice as sd
    import numpy as np

    chunk_samples = int(SAMPLE_RATE * CHUNK_SECS)
    silence_chunks_needed = int(SILENCE_DURATION_SECS / CHUNK_SECS)
    max_chunks = int(max_seconds / CHUNK_SECS)

    chunks: list[bytes] = []
    silence_count = 0
    done_evt = threading.Event()

    def callback(indata: "np.ndarray", frames: int, time_info, status) -> None:
        nonlocal silence_count
        mono = indata[:, 0].copy()
        chunks.append(mono.tobytes())

        # RMS energy (normalised 0..1)
        rms = float(np.sqrt(np.mean(mono.astype(np.float32) ** 2))) / 32768.0
        if on_energy:
            on_energy(rms)

        if rms < SILENCE_THRESHOLD_RMS:
            silence_count += 1
        else:
            silence_count = 0

        # Only auto-stop on silence *after* we have some speech (≥3 chunks with signal)
        has_speech = len(chunks) >= 3
        if has_speech and silence_count >= silence_chunks_needed:
            done_evt.set()
            raise sd.CallbackStop()
        if len(chunks) >= max_chunks:
            done_evt.set()
            raise sd.CallbackStop()

    stream_kwargs = dict(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        blocksize=chunk_samples,
        callback=callback,
    )
    if device_index is not None:
        stream_kwargs["device"] = device_index
    with sd.InputStream(**stream_kwargs):
        done_evt.wait(timeout=max_seconds + 2)

    return b"".join(chunks)


# ── arecord backend (Linux ALSA) ──────────────────────────────────────────

def _record_arecord(
    max_seconds: int = 30,
    on_energy: "callable | None" = None,
) -> bytes:
    """Record via arecord.  Silence detection done in Python on the piped PCM."""
    import numpy as np

    cmd = [
        "arecord",
        "-f", "S16_LE",
        "-r", str(SAMPLE_RATE),
        "-c", str(CHANNELS),
        "-t", "raw",
        "-q",
        "-d", str(max_seconds),
        "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    chunk_bytes = int(SAMPLE_RATE * CHUNK_SECS) * BYTES_PER_SAMPLE
    silence_chunks_needed = int(SILENCE_DURATION_SECS / CHUNK_SECS)

    chunks: list[bytes] = []
    silence_count = 0

    try:
        while True:
            raw = proc.stdout.read(chunk_bytes)
            if not raw:
                break
            chunks.append(raw)

            arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(arr ** 2))) / 32768.0
            if on_energy:
                on_energy(rms)

            if rms < SILENCE_THRESHOLD_RMS:
                silence_count += 1
            else:
                silence_count = 0

            has_speech = len(chunks) >= 3
            if has_speech and silence_count >= silence_chunks_needed:
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

    return b"".join(chunks)


# ── SoX rec backend ───────────────────────────────────────────────────────

def _record_sox(
    max_seconds: int = 30,
    on_energy: "callable | None" = None,
) -> bytes:
    """Record via SoX `rec` with built-in silence detection."""
    silence_threshold = "3%"
    silence_pre_duration = "0.1"
    silence_post_duration = str(SILENCE_DURATION_SECS)

    cmd = [
        "rec",
        "-q",
        "--buffer", "1024",
        "-t", "raw",
        "-r", str(SAMPLE_RATE),
        "-e", "signed",
        "-b", "16",
        "-c", str(CHANNELS),
        "-",
        "silence",
        "1", silence_pre_duration, silence_threshold,
        "1", silence_post_duration, silence_threshold,
    ]

    # Honour max_seconds via a timeout
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=max_seconds,
        )
        return result.stdout
    except subprocess.TimeoutExpired as e:
        return e.stdout or b""


# ── Public entry point ────────────────────────────────────────────────────

def record_until_silence(
    max_seconds: int = 30,
    on_energy: "callable | None" = None,
    device_index: "int | None" = None,
) -> bytes:
    """Record from microphone until silence or max_seconds.

    Returns raw PCM bytes: int16, 16 kHz, mono.
    Tries backends in order: sounddevice → arecord → sox rec.
    Raises RuntimeError if no backend is available.
    """
    try:
        import sounddevice  # noqa: F401
        return _record_sounddevice(max_seconds=max_seconds, on_energy=on_energy, device_index=device_index)
    except (ImportError, OSError):
        pass

    if _has_cmd("arecord"):
        try:
            import numpy  # noqa: F401
            return _record_arecord(max_seconds=max_seconds, on_energy=on_energy)
        except ImportError:
            # numpy missing — fall through to sox (no RMS feedback)
            return _record_arecord(max_seconds=max_seconds, on_energy=None)

    if _has_cmd("rec"):
        return _record_sox(max_seconds=max_seconds, on_energy=on_energy)

    raise RuntimeError(
        "No audio recording backend found.\n"
        "Install sounddevice:  pip install sounddevice\n"
        "Or install arecord:   sudo apt install alsa-utils\n"
        "Or install SoX:       sudo apt install sox"
    )
