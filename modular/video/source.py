"""
Source materials scanner for the video pipeline.

When the user provides a folder with images, audio, video, or text files,
this module scans it and feeds the content into the appropriate pipeline steps:

  images  → skip AI image generation, use these directly
  audio   → skip TTS, use this as narration
  text    → use as story context (summarised for the AI)
  video   → extract audio track and/or frames via ffmpeg
"""

import os
import re
import shutil

_IMAGE_EXT  = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
_AUDIO_EXT  = {'.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac'}
_VIDEO_EXT  = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv'}
_TEXT_EXT   = {'.txt', '.md', '.rst', '.csv', '.json', '.srt',
               '.pdf', '.docx', '.doc'}


def scan_source_dir(source_dir: str) -> dict:
    """
    Scan source_dir and return categorised lists of absolute file paths.

    Returns:
        {
          'images': [...],
          'audio':  [...],
          'video':  [...],
          'text':   [...],
        }
    """
    result = {'images': [], 'audio': [], 'video': [], 'text': []}
    if not os.path.isdir(source_dir):
        return result

    for fname in sorted(os.listdir(source_dir)):
        fpath = os.path.join(source_dir, fname)
        if not os.path.isfile(fpath):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext in _IMAGE_EXT:
            result['images'].append(fpath)
        elif ext in _AUDIO_EXT:
            result['audio'].append(fpath)
        elif ext in _VIDEO_EXT:
            result['video'].append(fpath)
        elif ext in _TEXT_EXT:
            result['text'].append(fpath)

    return result


def summarise_source_for_story(text_files: list[str], max_chars: int = 8000) -> str:
    """
    Read text files and return a combined excerpt suitable as story context.
    Truncates to max_chars total to avoid overwhelming the LLM.
    """
    parts = []
    total = 0
    for fpath in text_files:
        if total >= max_chars:
            break
        try:
            content = _read_text_file(fpath)
            if not content:
                continue
            snippet = content[: max_chars - total]
            parts.append(f"[{os.path.basename(fpath)}]\n{snippet}")
            total += len(snippet)
        except Exception as exc:
            print(f"  Could not read {fpath}: {exc}")
    return "\n\n".join(parts)


def _read_text_file(fpath: str) -> str:
    ext = os.path.splitext(fpath)[1].lower()
    if ext == '.pdf':
        return _read_pdf(fpath)
    if ext in ('.docx', '.doc'):
        return _read_docx(fpath)
    # Plain text / markdown / json / csv / srt / rst
    with open(fpath, encoding='utf-8', errors='replace') as f:
        return f.read()


def _read_pdf(fpath: str) -> str:
    try:
        import pypdf
        reader = pypdf.PdfReader(fpath)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        pass
    try:
        import pdfminer.high_level as pdfminer
        return pdfminer.extract_text(fpath)
    except ImportError:
        return f"[PDF: {os.path.basename(fpath)} — install pypdf or pdfminer.six to read]"


def _read_docx(fpath: str) -> str:
    try:
        import docx
        doc = docx.Document(fpath)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        return f"[DOCX: {os.path.basename(fpath)} — install python-docx to read]"


# ── AI-guided material relevance selection ───────────────────────────────────

def select_relevant_images(images: list[str], story_data: dict, n: int,
                           model: str | None = None, config: dict | None = None) -> list[str]:
    """
    From a pool of source images, select the n most relevant to the story.

    Strategy:
      1. If model + config provided: ask the LLM to rank by story relevance
      2. Fallback: keyword overlap between story text and image filenames
    Always returns exactly min(n, len(images)) paths.
    """
    if len(images) <= n:
        return images

    # 1. Model-based selection
    if model and config:
        selected = _model_select_images(images, story_data, n, model, config)
        if len(selected) >= 1:
            # Fill any gaps with keyword-scored images not already selected
            remaining = [p for p in images if p not in selected]
            kw_fill = _keyword_rank_images(remaining, story_data)
            for p in kw_fill:
                if len(selected) >= n:
                    break
                selected.append(p)
            return selected[:n]

    # 2. Keyword-based fallback
    return _keyword_rank_images(images, story_data)[:n]


def _model_select_images(images: list[str], story_data: dict, n: int,
                         model: str, config: dict) -> list[str]:
    """Use the LLM to select the most story-relevant images by filename."""
    try:
        from providers import stream, TextChunk  # type: ignore
        filenames = [os.path.basename(p) for p in images]
        story_brief = (story_data.get('title', '') + '\n\n'
                       + story_data.get('story', '')[:400])
        prompt = (
            f"Story:\n{story_brief}\n\n"
            f"Available image files:\n" + '\n'.join(f"- {f}" for f in filenames) + "\n\n"
            f"Select the {n} image files that best match this story visually. "
            f"Output ONLY the filenames, one per line, most relevant first. "
            f"No explanations, no bullet points, just filenames."
        )
        cfg = {**config, "max_tokens": 300, "temperature": 0.1, "stream": True}
        parts: list[str] = []
        for ev in stream(model, "You are an image curator.", [{"role": "user", "content": prompt}], [], cfg):
            if isinstance(ev, TextChunk):
                parts.append(ev.text)
        response = "".join(parts).strip()

        name_to_path = {os.path.basename(p): p for p in images}
        selected: list[str] = []
        for line in response.splitlines():
            name = line.strip().strip('*-•.,').strip()
            if name in name_to_path and name_to_path[name] not in selected:
                selected.append(name_to_path[name])
        return selected
    except Exception as exc:
        print(f"  Model image selection error: {exc}")
        return []


def _keyword_rank_images(images: list[str], story_data: dict) -> list[str]:
    """Rank images by keyword overlap between filename and story text."""
    story = (story_data.get('title', '') + ' ' + story_data.get('story', '')).lower()
    keywords = set(re.findall(r'[a-z]{3,}', story))
    # Remove very common words
    stop = {'the', 'and', 'was', 'for', 'not', 'but', 'had', 'his', 'her',
            'that', 'with', 'from', 'they', 'this', 'have', 'were', 'what'}
    keywords -= stop

    def score(path: str) -> int:
        name = re.sub(r'[_\-\s]+', ' ', os.path.splitext(os.path.basename(path))[0]).lower()
        name_words = set(re.findall(r'[a-z]{3,}', name))
        return len(keywords & name_words)

    return sorted(images, key=score, reverse=True)


# ── Source integration helpers for pipeline.py ───────────────────────────────

def copy_source_images(src_images: list[str], images_dir: str, is_short: bool = False) -> int:
    """
    Copy (and optionally resize) source images into images_dir.
    Returns number of images copied.
    """
    os.makedirs(images_dir, exist_ok=True)
    target_w, target_h = (1080, 1920) if is_short else (1920, 1080)
    count = 0
    for i, src in enumerate(src_images):
        dst = os.path.join(images_dir, f"img_{i:02d}{os.path.splitext(src)[1].lower()}")
        try:
            _resize_image(src, dst, target_w, target_h)
            count += 1
        except Exception as exc:
            print(f"  Image copy error ({os.path.basename(src)}): {exc}")
            try:
                shutil.copy2(src, dst)
                count += 1
            except Exception:
                pass
    print(f"  Source images: {count}/{len(src_images)} copied")
    return count


def _resize_image(src: str, dst: str, target_w: int, target_h: int):
    """Resize and centre-crop to target dimensions (requires Pillow)."""
    try:
        from PIL import Image
        img = Image.open(src).convert("RGB")
        img_ratio = img.width / img.height
        tgt_ratio = target_w / target_h
        if img_ratio > tgt_ratio:
            new_h = target_h
            new_w = int(new_h * img_ratio)
        else:
            new_w = target_w
            new_h = int(new_w / img_ratio)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (img.width  - target_w) // 2
        top  = (img.height - target_h) // 2
        img  = img.crop((left, top, left + target_w, top + target_h))
        img.save(dst, quality=95)
    except ImportError:
        shutil.copy2(src, dst)


def extract_audio_from_video(video_path: str, output_mp3: str) -> bool:
    """Extract audio track from a video file using ffmpeg."""
    import subprocess
    ff = shutil.which("ffmpeg")
    if not ff:
        try:
            from imageio_ffmpeg import get_ffmpeg_exe
            ff = get_ffmpeg_exe()
        except ImportError:
            pass
    if not ff:
        return False
    cmd = [ff, "-y", "-i", video_path, "-vn", "-codec:a", "libmp3lame", "-q:a", "2", output_mp3]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        return r.returncode == 0 and os.path.isfile(output_mp3)
    except Exception as exc:
        print(f"  Audio extraction error: {exc}")
        return False
