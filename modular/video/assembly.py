"""
FFmpeg-based video assembly for the video pipeline.
Handles: per-image zoompan clips → concat → audio → PIL subtitle burn.
"""

import os
import re as _re
import subprocess
import shutil
import urllib.request


# ── Font cache for subtitle rendering ────────────────────────────────────────
_FONT_CACHE = os.path.join(os.path.expanduser("~"), ".little-coder", "fonts")

# Download sources for a CJK-capable Unicode font (tried in order)
_FONT_SOURCES = [
    ("NotoSansSC-Regular.ttf",
     "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansSC/NotoSansSC-Regular.ttf"),
    ("NotoSansCJK-Regular.ttc",
     "https://github.com/googlefonts/noto-cjk/raw/main/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf"),
]


def _get_subtitle_font() -> tuple[str | None, str | None]:
    """
    Find or download a font with Unicode/CJK support.
    Returns (font_file_path, fontsdir) or (None, None).
    On first call downloads NotoSansSC and caches to ~/.little-coder/fonts/.
    """
    # 1. Cached font (fastest path after first run)
    os.makedirs(_FONT_CACHE, exist_ok=True)
    for fname, _ in _FONT_SOURCES:
        cached = os.path.join(_FONT_CACHE, fname)
        if os.path.isfile(cached) and os.path.getsize(cached) > 100_000:
            return cached, _FONT_CACHE

    # 2. Download (one-time)
    for fname, url in _FONT_SOURCES:
        cached = os.path.join(_FONT_CACHE, fname)
        try:
            print(f"  Downloading Unicode font for subtitles ({fname}) — one-time setup...")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            if len(data) > 100_000:
                with open(cached, "wb") as f:
                    f.write(data)
                print(f"  Font cached: {_FONT_CACHE}")
                return cached, _FONT_CACHE
            print(f"  Download too small ({len(data)} bytes), skipping")
        except Exception as exc:
            print(f"  Font download failed ({fname}): {exc}")

    # 3. System font fallback (Latin-only, no CJK)
    try:
        r = subprocess.run(["fc-list", "-f", "%{file}\n"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            p = line.strip()
            if p and os.path.isfile(p) and p.lower().endswith((".ttf", ".otf")):
                return p, os.path.dirname(p)
    except Exception:
        pass

    return None, None


QUALITY_PRESETS = {
    "high":    {"crf": "18", "preset": "slow",      "maxrate": "8M",  "bufsize": "16M"},
    "medium":  {"crf": "23", "preset": "medium",    "maxrate": "4M",  "bufsize": "8M"},
    "low":     {"crf": "28", "preset": "fast",      "maxrate": "2M",  "bufsize": "4M"},
    "minimal": {"crf": "32", "preset": "veryfast",  "maxrate": "1M",  "bufsize": "2M"},
}


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        return get_ffmpeg_exe()
    except ImportError:
        pass
    raise RuntimeError(
        "ffmpeg not found.\n"
        "No-sudo options:\n"
        "  pip install imageio-ffmpeg          (recommended)\n"
        "  conda install -c conda-forge ffmpeg\n"
        "  or download a static binary: https://johnvansickle.com/ffmpeg/"
    )


def _ffprobe() -> str:
    path = shutil.which("ffprobe")
    if path:
        return path
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        ffmpeg_path = get_ffmpeg_exe()
        probe_path = ffmpeg_path.replace("ffmpeg", "ffprobe")
        if os.path.isfile(probe_path):
            return probe_path
    except ImportError:
        pass
    return ""


def _audio_duration(audio_path: str) -> float:
    """Return audio duration in seconds. Uses ffprobe → ffmpeg -i → file-size fallback."""
    # 1. ffprobe (most accurate)
    probe = _ffprobe()
    if probe:
        try:
            result = subprocess.run(
                [probe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
                capture_output=True, text=True, timeout=10
            )
            return float(result.stdout.strip())
        except Exception:
            pass

    # 2. Parse duration from `ffmpeg -i` stderr
    try:
        ff = _ffmpeg()
        r = subprocess.run([ff, "-i", audio_path], capture_output=True, text=True, timeout=15)
        for line in (r.stdout + r.stderr).splitlines():
            if "Duration:" in line:
                m = _re.search(r'Duration:\s*(\d+):(\d+):(\d+\.?\d*)', line)
                if m:
                    h, mn, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
                    dur = h * 3600 + mn * 60 + s
                    if dur > 0:
                        return dur
    except Exception:
        pass

    # 3. File-size estimate (Edge TTS ~48kbps = 6kB/s)
    try:
        return os.path.getsize(audio_path) / 6000
    except OSError:
        return 120.0


def mix_sfx(main_audio: str, sfx_cues: list[dict], sounds_dir: str) -> str:
    """
    Overlay SFX files onto main_audio at given timestamps.
    sfx_cues: list of {'seconds': int, 'name': str}
    Returns path to mixed audio (or main_audio if nothing was mixed).
    """
    ff = _ffmpeg()
    valid = []
    for cue in sfx_cues:
        for ext in ('.mp3', '.wav', '.ogg'):
            fp = os.path.join(sounds_dir, f"{cue['name']}{ext}")
            if os.path.isfile(fp):
                valid.append({'path': fp, 'seconds': cue['seconds']})
                break
    if not valid:
        return main_audio

    out_path = main_audio.replace('.mp3', '_sfx.mp3')
    inputs = ["-i", main_audio]
    filter_parts = ["[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[main]"]
    mix_inputs = ["[main]"]

    for i, cue in enumerate(valid, 1):
        inputs += ["-i", cue['path']]
        delay_ms = cue['seconds'] * 1000
        lbl = f"sfx{i}"
        filter_parts.append(
            f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms},volume=0.15[{lbl}]"
        )
        mix_inputs.append(f"[{lbl}]")

    n = len(mix_inputs)
    filter_parts.append(f"{''.join(mix_inputs)}amix=inputs={n}:duration=first:dropout_transition=3[out]")
    fc = ";".join(filter_parts)

    cmd = [ff, "-y"] + inputs + ["-filter_complex", fc, "-map", "[out]",
                                  "-codec:a", "libmp3lame", "-q:a", "2", out_path]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.isfile(out_path):
            print(f"  SFX mixed: {len(valid)} effect(s)")
            return out_path
    except Exception as exc:
        print(f"  SFX mix error: {exc}")
    return main_audio


# ── PIL subtitle rendering ────────────────────────────────────────────────────

def _parse_srt(srt_path: str) -> list[tuple[float, float, str]]:
    """Parse SRT file into list of (start_sec, end_sec, text) tuples."""
    entries = []
    try:
        with open(srt_path, encoding='utf-8', errors='replace') as f:
            content = f.read()
        # Split into blocks separated by blank lines
        blocks = _re.split(r'\n\n+', content.strip())
        for block in blocks:
            lines = [l.rstrip() for l in block.strip().split('\n')]
            if len(lines) < 2:
                continue
            # Find the timestamp line (may be lines[0] or lines[1])
            ts_idx = None
            for j, line in enumerate(lines):
                m = _re.match(
                    r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*'
                    r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})',
                    line.strip()
                )
                if m:
                    h1, m1, s1, ms1 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                    h2, m2, s2, ms2 = int(m.group(5)), int(m.group(6)), int(m.group(7)), int(m.group(8))
                    start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
                    end   = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
                    ts_idx = (j, start, end)
                    break
            if ts_idx is None:
                continue
            text_lines = lines[ts_idx[0] + 1:]
            text = ' '.join(l for l in text_lines if l)
            # Strip HTML tags (<i>, <b>, etc.)
            text = _re.sub(r'<[^>]+>', '', text).strip()
            if text:
                entries.append((ts_idx[1], ts_idx[2], text))
    except Exception as exc:
        print(f"  SRT parse error: {exc}")
    return entries


def _render_subtitle_image(text: str, font_path: str, font_size: int,
                            max_width: int):
    """
    Render subtitle text as a transparent RGBA PIL Image.
    Supports word-wrap for long lines. Returns PIL Image or None.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont

        font = ImageFont.truetype(font_path, font_size)

        # ── Word-wrap (Latin) or character-wrap (CJK no spaces) ──────────────
        dummy = Image.new("RGBA", (1, 1))
        ddraw = ImageDraw.Draw(dummy)

        def _text_width(t):
            bb = ddraw.textbbox((0, 0), t, font=font)
            return bb[2] - bb[0]

        # Split by existing newlines first, then wrap each part
        raw_lines = text.split('\n')
        lines = []
        for raw in raw_lines:
            words = raw.split()
            if not words:
                # CJK: no spaces — wrap by character count
                # estimate chars per line from max_width
                est_char_w = _text_width('中')  # representative CJK char
                if est_char_w > 0:
                    cpl = max(1, int(max_width / est_char_w))
                    for i in range(0, len(raw), cpl):
                        lines.append(raw[i:i+cpl])
                else:
                    lines.append(raw)
            else:
                # CJK text with no spaces: split() returns the whole string as one word
                if len(words) == 1 and _text_width(words[0]) > max_width:
                    # character-level wrap
                    chunk = ''
                    for ch in words[0]:
                        if _text_width(chunk + ch) > max_width and chunk:
                            lines.append(chunk)
                            chunk = ch
                        else:
                            chunk += ch
                    if chunk:
                        lines.append(chunk)
                else:
                    # Latin: word-level wrap
                    cur = []
                    for word in words:
                        test = ' '.join(cur + [word])
                        if _text_width(test) > max_width and cur:
                            lines.append(' '.join(cur))
                            cur = [word]
                        else:
                            cur.append(word)
                    if cur:
                        lines.append(' '.join(cur))

        if not lines:
            return None

        # ── Measure all lines ──────────────────────────────────────────────────
        line_bboxes = [ddraw.textbbox((0, 0), ln, font=font) for ln in lines]
        line_widths  = [bb[2] - bb[0] for bb in line_bboxes]
        line_heights = [bb[3] - bb[1] for bb in line_bboxes]
        line_spacing = max(4, int(font_size * 0.25))
        total_w = max(line_widths)
        total_h = sum(line_heights) + line_spacing * (len(lines) - 1)

        pad     = max(8, font_size // 4)
        outline = max(2, font_size // 18)
        img_w   = total_w + pad * 2
        img_h   = total_h + pad * 2

        img  = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        y = pad
        for i, line in enumerate(lines):
            lw  = line_widths[i]
            lh  = line_heights[i]
            x   = pad + (total_w - lw) // 2  # center each line
            # Black outline
            for dx in range(-outline, outline + 1):
                for dy in range(-outline, outline + 1):
                    if dx != 0 or dy != 0:
                        draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0, 220))
            # White text
            draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
            y += lh + line_spacing

        return img

    except Exception as exc:
        print(f"  PIL subtitle render error: {exc}")
        return None


def _burn_subtitles_pil(input_video: str, output_video: str, srt_file: str,
                         is_short: bool = False, quality: str = "high") -> bool:
    """
    Burn subtitles into video using PIL rendering + ffmpeg overlay filter.
    Bypasses libass entirely — renders any Unicode text (CJK, Cyrillic, etc.).
    Returns True on success.
    """
    import tempfile

    # Check PIL
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("  Pillow not installed — pip install Pillow for subtitle rendering")
        return False

    entries = _parse_srt(srt_file)
    if not entries:
        print("  No SRT entries found — skipping subtitle burn")
        return False

    font_path, _ = _get_subtitle_font()
    if not font_path:
        print("  No font available for PIL subtitle rendering")
        return False

    font_size     = 52 if is_short else 48
    res_w         = 1080 if is_short else 1920
    margin_bottom = 80 if is_short else 60
    max_text_w    = int(res_w * 0.85)

    tmp_dir = tempfile.mkdtemp(prefix="cc_subs_")
    sub_files: list[tuple[str, float, float]] = []  # (png_path, start, end)

    try:
        for i, (start, end, text) in enumerate(entries):
            img = _render_subtitle_image(text, font_path, font_size, max_text_w)
            if img is None:
                continue
            png_path = os.path.join(tmp_dir, f"sub_{i:04d}.png")
            img.save(png_path, format='PNG')
            sub_files.append((png_path, start, end))

        if not sub_files:
            print("  No subtitle images rendered")
            return False

        print(f"  PIL rendered {len(sub_files)}/{len(entries)} subtitle entries")

        ff  = _ffmpeg()
        q   = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["high"])

        # ── Build ffmpeg command ──────────────────────────────────────────────
        # Input 0: source video (already has audio)
        # Input 1..N: subtitle PNG images
        inputs = [ff, "-y", "-i", input_video]
        for png_path, _, _ in sub_files:
            inputs += ["-i", png_path]

        # Chain overlay filters:
        # [prev][N:v]overlay=x=...:y=...:enable='between(t,start,end)'[vN]
        filter_parts = []
        prev = "0:v"
        for i, (_, start, end) in enumerate(sub_files):
            src = f"{i + 1}:v"
            out = f"v{i + 1}" if i < len(sub_files) - 1 else "vfinal"
            filter_parts.append(
                f"[{prev}][{src}]overlay="
                f"x=(W-w)/2:y=H-h-{margin_bottom}:"
                f"enable='between(t,{start:.3f},{end:.3f})'"
                f"[{out}]"
            )
            prev = out

        cmd = (inputs + [
            "-filter_complex", ";".join(filter_parts),
            "-map", "[vfinal]", "-map", "0:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-crf", q["crf"], "-preset", q["preset"],
            "-maxrate", q["maxrate"], "-bufsize", q["bufsize"],
            "-c:a", "copy",
            output_video
        ])

        r = subprocess.run(cmd, capture_output=True, timeout=900)
        if r.returncode == 0 and os.path.isfile(output_video):
            print("  Subtitles burned successfully (PIL)")
            return True
        else:
            err = r.stderr.decode(errors='replace')
            for line in err.splitlines():
                if 'error' in line.lower() or 'invalid' in line.lower():
                    print(f"  PIL subtitle ffmpeg error: {line.strip()}")
                    break
            return False

    except Exception as exc:
        print(f"  PIL subtitle burn error: {exc}")
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Main video assembly ───────────────────────────────────────────────────────

def create_video(images_dir: str, audio_file: str, output_file: str,
                 srt_file: str | None = None,
                 image_timestamps: list[dict] | None = None,
                 is_short: bool = False,
                 quality: str = "high") -> bool:
    """
    Assemble final video from images + audio (+ optional PIL subtitle burn).

    images_dir:       directory containing img_*.png / *.jpg files
    audio_file:       MP3/WAV narration
    output_file:      destination .mp4
    srt_file:         optional SRT subtitle file to burn in (uses PIL — works for all languages)
    image_timestamps: list of {'seconds': int|None} aligned with sorted image list
    is_short:         True for 9:16 vertical (1080×1920), False for 16:9 (1920×1080)
    quality:          "high" | "medium" | "low" | "minimal"
    """
    ff = _ffmpeg()
    duration = _audio_duration(audio_file)
    res_w, res_h = (1080, 1920) if is_short else (1920, 1080)

    images = sorted([
        f for f in os.listdir(images_dir)
        if f.lower().endswith(('.png', '.jpg', '.jpeg')) and not f.startswith('clip_')
    ])
    if not images:
        print("  No images found in images_dir")
        return False

    # ── Compute per-image durations ───────────────────────────────────────────
    if image_timestamps and len(image_timestamps) == len(images):
        start_times = [ts.get('seconds') or 0 for ts in image_timestamps]
        max_ts = max(start_times) if start_times else 0
        if max_ts > 0 and (max_ts > duration * 0.9 or max_ts < duration * 0.5):
            scale = (duration * 0.85) / max_ts
            start_times = [s * scale for s in start_times]
            print(f"  Timestamps scaled by {scale:.2f}x to match audio ({duration:.0f}s)")
        durations = []
        for i, st in enumerate(start_times):
            nxt = start_times[i + 1] if i + 1 < len(start_times) else duration
            dur = max(4.0, min(nxt - st, duration - st))
            if i == len(start_times) - 1:
                dur = max(dur, duration - st)
            durations.append(dur)
        total = sum(durations)
        if total < duration + 2:
            durations[-1] += (duration + 2) - total
    else:
        dur_each = duration / len(images)
        durations = [dur_each] * len(images)
        print(f"  Uniform distribution: {len(images)} images × {dur_each:.1f}s")

    # Always add a 2-second hold on the last frame
    durations[-1] += 2.0

    fps = 30
    q   = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["high"])

    # ── Generate one zoompan clip per image ───────────────────────────────────
    clip_files = []
    for i, img in enumerate(images):
        d_frames   = max(1, int(durations[i] * fps))
        zoom_speed = round(0.5 / d_frames, 6)
        clip_path  = os.path.join(images_dir, f"clip_{i:03d}.mp4")
        img_path   = os.path.join(images_dir, img)

        vf = (f"scale={res_w}:{res_h}:force_original_aspect_ratio=decrease,"
              f"pad={res_w}:{res_h}:(ow-iw)/2:(oh-ih)/2,format=yuv420p,"
              f"zoompan=z='min(zoom+{zoom_speed},1.5)':d={d_frames}:s={res_w}x{res_h}")

        cmd = [ff, "-y", "-loop", "1", "-i", img_path, "-vf", vf,
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
               "-t", str(durations[i]), "-crf", "1", "-preset", "ultrafast", "-an", clip_path]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=180)
            if r.returncode == 0 and os.path.isfile(clip_path):
                clip_files.append(clip_path)
            else:
                print(f"  Warning: clip {i+1} failed")
        except Exception as exc:
            print(f"  Clip {i+1} error: {exc}")

    if not clip_files:
        print("  No video clips generated")
        return False

    # ── Concatenate clips ─────────────────────────────────────────────────────
    concat_list = os.path.join(images_dir, "clips.txt")
    with open(concat_list, 'w', encoding='utf-8') as f:
        for cp in clip_files:
            f.write(f"file '{cp}'\n")

    base_cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-i", audio_file]

    has_srt = bool(srt_file and os.path.isfile(srt_file))
    success = False

    if has_srt:
        # ── Two-pass subtitle approach ────────────────────────────────────────
        # Pass 1: fast assembly (copy video stream — no re-encode)
        tmp_video = output_file.replace('.mp4', '_notitles.mp4')
        cmd_raw = base_cmd + [
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", tmp_video
        ]
        print(f"  Assembling clips (pass 1)...")
        try:
            r1 = subprocess.run(cmd_raw, capture_output=True, timeout=300)
            if r1.returncode == 0 and os.path.isfile(tmp_video):
                # Pass 2: PIL subtitle burn
                print(f"  Burning subtitles (pass 2, PIL)...")
                pil_ok = _burn_subtitles_pil(tmp_video, output_file, srt_file, is_short, quality)
                try:
                    os.remove(tmp_video)
                except OSError:
                    pass
                if pil_ok:
                    success = True
                else:
                    # PIL failed — re-encode without subtitles using quality preset
                    print("  PIL subtitles failed — encoding without subtitles")
                    cmd_enc = base_cmd + [
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
                        "-crf", q["crf"], "-preset", q["preset"],
                        "-maxrate", q["maxrate"], "-bufsize", q["bufsize"],
                        "-c:a", "aac", "-b:a", "192k", "-shortest", output_file
                    ]
                    r2 = subprocess.run(cmd_enc, capture_output=True, timeout=600)
                    success = r2.returncode == 0 and os.path.isfile(output_file)
                    if not success:
                        print(f"  FFmpeg error: {r2.stderr.decode(errors='replace')[-400:]}")
            else:
                print(f"  Pass 1 failed: {r1.stderr.decode(errors='replace')[-300:]}")
        except Exception as exc:
            print(f"  Assembly error: {exc}")
            if os.path.isfile(tmp_video):
                try:
                    os.remove(tmp_video)
                except OSError:
                    pass
    else:
        # ── Single-pass: encode with quality preset, no subtitles ─────────────
        print(f"  Encoding video (quality={quality})...")
        cmd_enc = base_cmd + [
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
            "-crf", q["crf"], "-preset", q["preset"],
            "-maxrate", q["maxrate"], "-bufsize", q["bufsize"],
            "-c:a", "aac", "-b:a", "192k", "-shortest", output_file
        ]
        try:
            r = subprocess.run(cmd_enc, capture_output=True, timeout=600)
            success = r.returncode == 0 and os.path.isfile(output_file)
            if not success:
                print(f"  FFmpeg error: {r.stderr.decode(errors='replace')[-400:]}")
        except Exception as exc:
            print(f"  FFmpeg encode error: {exc}")

    # ── Clean up temp clips ───────────────────────────────────────────────────
    for cp in clip_files:
        try:
            os.remove(cp)
        except OSError:
            pass
    try:
        os.remove(concat_list)
    except OSError:
        pass

    return success
