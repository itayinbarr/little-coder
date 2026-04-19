"""
Main video pipeline orchestration.
Ties together: story → TTS → subtitles → images → video assembly.
"""

import os
import json
import re
from datetime import datetime
from pathlib import Path


def _safe_filename(title: str, max_len: int = 50) -> str:
    """Convert a story title to a safe ASCII filesystem name."""
    # Strip non-ASCII (CJK, etc.) — keep only printable ASCII
    s = re.sub(r'[^\x20-\x7E]', '', title)
    s = re.sub(r'[^\w\s-]', '', s).strip()
    s = re.sub(r'[\s-]+', '_', s)
    s = s[:max_len].lower().strip('_')
    return s or "video"


def create_video_story(
    topic: str,
    model: str,
    config: dict,
    *,
    script_text: str | None = None,
    niche_name: str | None = None,
    duration_min: float | None = None,
    is_short: bool = False,
    tts_engine: str = "auto",
    tts_voice: str = "Charon",
    edge_voice: str = "en-US-GuyNeural",
    image_engine: str = "auto",
    subtitle_lang: str = "en",
    subtitle_text: str | None = None,
    quality: str = "high",
    output_dir: str | None = None,
    work_dir: str | None = None,
    sounds_dir: str | None = None,
    source_dir: str | None = None,
    story_lang_instr: str = "",
) -> dict | None:
    """
    Full pipeline: topic → .mp4

    script_text: if provided, skip AI story generation and use this text directly
      as the narration (TTS reads it) and subtitles. Overrides topic.

    source_dir: optional folder with user-provided materials
      - images  → used directly instead of AI-generated images
      - audio   → used as narration instead of TTS
      - video   → audio track extracted and used as narration
      - text    → read and injected as story context

    subtitle_text controls subtitle source:
      None          → Whisper auto-transcription (default)
                      (when script_text is set, defaults to "__story__" automatically)
      ""            → no subtitles
      "__story__"   → use the narration text as subtitles
      "<your text>" → burn this custom text as subtitles

    Returns a result dict with keys:
        video_path, title, word_count, niche_id,
        audio_path, srt_path, images_dir, work_dir
    or None on failure.
    """
    from .story     import generate_story
    from .tts       import generate_audio
    from .subtitles import generate_subtitles  # used for Whisper path

    # When a custom script is provided and no explicit subtitle choice was made,
    # default to showing the script text as subtitles.
    if script_text and subtitle_text is None:
        subtitle_text = "__story__"
    from .images    import generate_images
    from .assembly  import create_video, mix_sfx

    # ── Source materials scan ─────────────────────────────────────────────────
    src_info = {'images': [], 'audio': [], 'video': [], 'text': []}
    if source_dir:
        from .source import scan_source_dir, summarise_source_for_story, copy_source_images, extract_audio_from_video
        src_info = scan_source_dir(source_dir)
        # Enrich topic with text content
        if src_info['text'] and not topic:
            topic = summarise_source_for_story(src_info['text'])
        elif src_info['text']:
            topic = topic + "\n\nSource context:\n" + summarise_source_for_story(src_info['text'], max_chars=3000)

    # ── Directories ───────────────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = output_dir or os.path.join(os.getcwd(), "video_output")
    tmp  = work_dir  or os.path.join(os.getcwd(), "video_tmp",  f"batch_{ts}")
    os.makedirs(base, exist_ok=True)
    os.makedirs(tmp,  exist_ok=True)

    story_dir  = os.path.join(tmp, "story")
    images_dir = os.path.join(story_dir, "images")
    os.makedirs(story_dir,  exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)

    # ── Step 1: Story generation (or use custom script) ──────────────────────
    if script_text:
        print(f"\n[1/5] Using custom script ({len(script_text.split())} words)...")
        story_text = script_text.strip()

        # Derive a short title (first sentence, max 8 Latin words or 20 CJK chars)
        first = re.split(r'[.!?\n。！？]', story_text)[0].strip()
        if first:
            words = first.split()
            if len(words) <= 1 and len(first) > 20:
                # CJK/no-space: trim to first 20 chars
                title = first[:20]
            else:
                title = ' '.join(words[:8])
        else:
            title = topic or "Custom Script"

        # Build evenly-spaced image prompts from story sentences
        sentences = [s.strip() for s in re.split(r'[.!?\n。！？]', story_text) if len(s.strip()) > 8]
        num_imgs  = min(8, max(4, len(sentences) // 3 + 1))
        dur_est   = max(10, len(story_text.split()) / 2.5)   # rough seconds
        img_style = "cinematic photography, photorealistic, dramatic lighting"
        image_prompts = []
        for i in range(num_imgs):
            secs      = int(i * dur_est / max(num_imgs - 1, 1))
            mm, ss    = divmod(secs, 60)
            si        = int(i * len(sentences) / num_imgs) if sentences else 0
            sent_ctx  = sentences[si] if si < len(sentences) else story_text[:80]
            image_prompts.append({
                'prompt': f"{sent_ctx[:120]}, {img_style}",
                'timestamp': f"{mm}:{ss:02d}",
                'seconds': secs,
            })

        story_data = {
            'title':         title,
            'story':         story_text,
            'niche_id':      'custom',
            'niche':         {'nombre': 'Custom Script', 'imagen_estilo': img_style},
            'image_prompts': image_prompts,
            'sfx_cues':      [],
            'has_timestamps': True,
        }
        print(f"  Title: {title}")
        print(f"  Words: {len(story_text.split())} | Images: {num_imgs}")
    else:
        target_words = int(duration_min * 135) if duration_min else (90 if is_short else None)
        print(f"\n[1/5] Generating story...")
        story_data = generate_story(
            topic        = topic,
            model        = model,
            config       = config,
            niche_name   = niche_name,
            target_words = target_words,
            is_short     = is_short,
            lang_instr   = story_lang_instr,
        )
        if not story_data:
            print("  Story generation failed.")
            return None

        title      = story_data['title']
        story_text = story_data['story']
        print(f"  Title: {title}")
        print(f"  Words: {len(story_text.split())} | Images: {len(story_data['image_prompts'])}")

    # Save story text
    with open(os.path.join(story_dir, "story.txt"), 'w', encoding='utf-8') as f:
        f.write(f"Title: {title}\n\n{story_text}")

    # ── Step 2: Audio (TTS or source) ────────────────────────────────────────
    audio_path = os.path.join(story_dir, "audio.mp3")

    # Source audio: use provided audio directly
    if src_info['audio']:
        import shutil as _shutil
        _shutil.copy2(src_info['audio'][0], audio_path)
        print(f"\n[2/5] Using source audio: {os.path.basename(src_info['audio'][0])}")
    # Source video: extract audio track
    elif src_info['video']:
        from .source import extract_audio_from_video
        print(f"\n[2/5] Extracting audio from source video: {os.path.basename(src_info['video'][0])}")
        if not extract_audio_from_video(src_info['video'][0], audio_path):
            print("  Audio extraction failed — falling back to TTS.")
            src_info['video'] = []

    if not os.path.isfile(audio_path):
        print(f"\n[2/5] Generating voice ({tts_engine})...")
        if not generate_audio(story_text, audio_path, engine=tts_engine, voice=tts_voice, edge_voice=edge_voice):
            print("  Audio generation failed.")
            return None
        print(f"  Audio saved: {audio_path}")

    # Mix SFX if available
    if story_data.get('sfx_cues') and sounds_dir and os.path.isdir(sounds_dir):
        audio_path = mix_sfx(audio_path, story_data['sfx_cues'], sounds_dir)

    # ── Step 3: Subtitles ─────────────────────────────────────────────────────
    srt_path = os.path.join(story_dir, "subs.srt")
    print(f"\n[3/5] Generating subtitles...")

    if subtitle_text == "":
        # Explicitly disabled
        srt_path = None
        print("  Subtitles disabled")
    elif subtitle_text is not None:
        # Custom or story text → text_to_srt (no Whisper needed, works for all languages)
        from .subtitles import text_to_srt
        _sub_text = story_text if subtitle_text == "__story__" else subtitle_text
        srt_ok = text_to_srt(_sub_text, audio_path, srt_path)
        if not srt_ok:
            srt_path = None
    else:
        # Auto: Whisper transcription
        srt_ok = generate_subtitles(audio_path, srt_path, language=subtitle_lang)
        if not srt_ok:
            srt_path = None

    # ── Step 4: Images (source or AI-generated) ───────────────────────────────
    img_count   = 0
    num_prompts = len(story_data.get('image_prompts', [])) or 4
    # Story context for relevance scoring and AI query generation
    story_context = story_data.get('title', '') + '\n' + story_data.get('story', '')

    # Source images: select the most relevant ones, then copy
    if src_info['images']:
        from .source import copy_source_images, select_relevant_images
        pool = src_info['images']
        if len(pool) > num_prompts:
            print(f"\n[4/5] Selecting {num_prompts} best images from {len(pool)} source files...")
            pool = select_relevant_images(pool, story_data, num_prompts,
                                          model=model, config=config)
            print(f"  Selected: {[os.path.basename(p) for p in pool]}")
        else:
            print(f"\n[4/5] Using {len(pool)} source image(s)...")
        img_count = copy_source_images(pool, images_dir, is_short)

    # Source video: extract frames
    if img_count == 0 and src_info['video']:
        img_count = _extract_video_frames(src_info['video'][0], images_dir, is_short)

    # AI image generation (fallback when no source images)
    if img_count == 0:
        prompts = story_data.get('image_prompts', [])
        niche_style = story_data['niche'].get('imagen_estilo', '')
        styled_prompts = []
        for p in prompts:
            full_prompt = p['prompt']
            if niche_style and niche_style.split(',')[0].lower() not in full_prompt.lower():
                full_prompt = f"{full_prompt}, {niche_style}"
            styled_prompts.append({**p, 'prompt': full_prompt})

        if not styled_prompts:
            print("\n[4/5] No image prompts found — using placeholders.")
            styled_prompts = [{'prompt': f"Scene {i+1}: {title}", 'timestamp': None, 'seconds': None}
                             for i in range(4)]

        print(f"\n[4/5] Generating {len(styled_prompts)} image(s) ({image_engine})...")
        img_count = generate_images(
            styled_prompts, images_dir,
            engine       = image_engine,
            is_short     = is_short,
            story_context= story_context,
            model        = model,
            config       = config,
        )
        # Use prompts for timestamps
        story_data['_styled_prompts'] = styled_prompts

    if img_count == 0:
        print("  No images available — pipeline cannot continue.")
        return None
    print(f"  {img_count} image(s) ready")

    # Timestamps for assembly (from AI prompts if available, otherwise uniform)
    styled_prompts = story_data.get('_styled_prompts', story_data.get('image_prompts', []))
    timestamps = [{'seconds': p.get('seconds')} for p in styled_prompts] if styled_prompts else []

    # ── Step 5: Video assembly ────────────────────────────────────────────────
    safe_name  = _safe_filename(title)
    video_name = f"video_{ts}_{safe_name}.mp4"
    video_path = os.path.join(base, video_name)

    print(f"\n[5/5] Assembling video...")
    success = create_video(
        images_dir       = images_dir,
        audio_file       = audio_path,
        output_file      = video_path,
        srt_file         = srt_path,
        image_timestamps = timestamps,
        is_short         = is_short,
        quality          = quality,
    )

    if not success:
        print("  Video assembly failed.")
        return None

    size_mb = os.path.getsize(video_path) / 1_048_576
    print(f"\n  Video ready: {video_path} ({size_mb:.1f} MB)")

    # ── Save metadata JSON ─────────────────────────────────────────────────────
    meta = {
        "version":   "1.0",
        "created_at": datetime.now().isoformat(),
        "video": {
            "filename": video_name,
            "title":    title,
            "is_short": is_short,
            "quality":  quality,
            "size_mb":  round(size_mb, 2),
        },
        "content": {
            "niche_id":   story_data['niche_id'],
            "niche_name": story_data['niche']['nombre'],
            "topic":      topic,
            "word_count": len(story_text.split()),
            "story":      story_text[:500] + "..." if len(story_text) > 500 else story_text,
        },
        "production": {
            "model":        model,
            "tts_engine":   tts_engine,
            "image_engine": image_engine,
            "image_count":  img_count,
            "subtitles":    srt_path is not None,
            "source_dir":   source_dir,
        },
    }
    meta_path = video_path.replace('.mp4', '_info.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return {
        "video_path":  video_path,
        "title":       title,
        "word_count":  len(story_text.split()),
        "niche_id":    story_data['niche_id'],
        "audio_path":  audio_path,
        "srt_path":    srt_path,
        "images_dir":  images_dir,
        "work_dir":    tmp,
        "meta_path":   meta_path,
        "size_mb":     round(size_mb, 2),
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_video_frames(video_path: str, images_dir: str, is_short: bool = False) -> int:
    """
    Extract evenly-spaced frames from a video file using ffmpeg.
    Returns number of frames extracted.
    """
    import shutil
    import subprocess
    ff = shutil.which("ffmpeg")
    if not ff:
        try:
            from imageio_ffmpeg import get_ffmpeg_exe
            ff = get_ffmpeg_exe()
        except ImportError:
            return 0

    os.makedirs(images_dir, exist_ok=True)
    # Extract 6 frames evenly spaced (fps=1/Ns selects 1 frame every N seconds)
    out_pattern = os.path.join(images_dir, "img_%02d.jpg")
    cmd = [ff, "-y", "-i", video_path,
           "-vf", "fps=1/5,scale=1920:1080:force_original_aspect_ratio=decrease",
           "-frames:v", "8", out_pattern]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60)
    except Exception as exc:
        print(f"  Frame extraction error: {exc}")
        return 0

    frames = [f for f in os.listdir(images_dir) if f.endswith('.jpg')]
    print(f"  Extracted {len(frames)} frame(s) from source video")
    return len(frames)
