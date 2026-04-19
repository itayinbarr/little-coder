"""Voice package for little-coder.

Public API
----------
check_voice_deps()   → (available: bool, reason: str | None)
record_once(...)     → raw PCM bytes  (int16, 16 kHz, mono)
transcribe(...)      → text string
voice_input(...)     → transcribed text (record + transcribe in one call)
"""

from .recorder import check_recording_availability, record_until_silence, list_input_devices
from .stt import check_stt_availability, transcribe, transcribe_audio_file
from .keyterms import get_voice_keyterms


def check_voice_deps() -> tuple[bool, str | None]:
    """Return (available, reason_if_not)."""
    rec_ok, rec_reason = check_recording_availability()
    if not rec_ok:
        return False, rec_reason
    stt_ok, stt_reason = check_stt_availability()
    if not stt_ok:
        return False, stt_reason
    return True, None


def voice_input(
    language: str = "auto",
    max_seconds: int = 30,
    on_energy: "callable | None" = None,
    device_index: "int | None" = None,
) -> str:
    """Record until silence, then transcribe.  Returns transcribed text."""
    keyterms = get_voice_keyterms()
    pcm = record_until_silence(max_seconds=max_seconds, on_energy=on_energy, device_index=device_index)
    if not pcm:
        return ""
    return transcribe(pcm, keyterms=keyterms, language=language)


__all__ = [
    "check_voice_deps",
    "check_recording_availability",
    "check_stt_availability",
    "record_until_silence",
    "list_input_devices",
    "transcribe",
    "transcribe_audio_file",
    "get_voice_keyterms",
    "voice_input",
]
