"""
Story generation for video pipeline.
Uses little-coder' active provider (stream()) — no separate litellm dependency.
"""

import re
import random
from .niches import select_niche, parse_timestamp


def generate_story(topic: str, model: str, config: dict,
                   niche_name: str | None = None,
                   target_words: int | None = None,
                   is_short: bool = False,
                   lang_instr: str = "") -> dict | None:
    """
    Generate a viral story with image prompts and SFX cues.

    Returns a dict with keys:
        title, story, niche_id, niche, image_prompts, sfx_cues, has_timestamps
    or None on failure.

    image_prompts: list of {'prompt': str, 'timestamp': str|None, 'seconds': int|None}
    sfx_cues:      list of {'timestamp': str, 'seconds': int, 'name': str}
    """
    from providers import stream, TextChunk  # type: ignore

    niche_id, niche = select_niche(niche_name)
    print(f"  Target niche: {niche['nombre']}")

    hook_examples = random.sample(niche['hooks'], min(3, len(niche['hooks'])))
    hooks_text = "\n".join(f'  - "{h}"' for h in hook_examples)
    title_examples = ", ".join(f'"{t}"' for t in niche['titulo_ejemplos'])
    cliches = ", ".join(niche['cliches_prohibidos'])

    context_block = f"\nUSER CREATIVE DIRECTION (integrate with the niche):\n{topic}\n" if topic else ""
    lang_block = f"\n=== LANGUAGE REQUIREMENT ===\n{lang_instr}\n" if lang_instr else ""

    if target_words:
        word_rule = (f"- MANDATORY LENGTH: ~{target_words} words (±30 words). "
                     f"If you write fewer than {int(target_words * 0.85)} words the story will be rejected.")
    elif is_short:
        word_rule = "- Between 80 and 110 words (SHORT — max 60-second video)"
    else:
        word_rule = "- Between 300 and 450 words (complete story with development, do NOT write fewer than 300)"

    prompt = f"""You are a viral content writer for YouTube/TikTok. Your specialty: {niche['nombre']}.

GENERATE 1 story with VIRAL potential using these narrative techniques.
{context_block}{lang_block}
=== NICHE IDENTITY ===
- TONE: {niche['tono']}
- NARRATIVE STYLE: {niche['narrativa']}

=== VIRAL TECHNIQUES (MANDATORY) ===
1. HOOK (first sentence): MUST stop the scroll — instant curiosity, tension, or shock.
   Draw inspiration from these niche hooks:
{hooks_text}
2. ESCALATION: Every paragraph must increase tension/emotion. No boring plateaus.
3. SENSORY DETAILS: Smells, textures, specific sounds — don't describe, make them FEEL.
4. PUNCHY DIALOGUE: At least 1-2 lines of dialogue that hit hard.
5. TWIST/CLOSE: Ending that leaves the viewer processing. Revelation, irony, ambiguity, or emotional punch.

=== STORY RULES ===
{word_rule}
- First person ("I", "my") — the viewer must feel you are telling THEM directly
- FORBIDDEN clichés for this niche: {cliches}
- FORBIDDEN: flowery prose, excessive metaphors, unnecessary descriptions
- YES: short sentences for tense moments, paragraphs that breathe
- Natural language (not too formal, not excessive slang)

=== TITLE RULES (CRITICAL FOR CTR) ===
- The title SELLS the story — must create irresistible curiosity
- Use ONLY Latin characters (A-Z, accented letters, numbers)
- Maximum 8 words — short, punchy, memorable
- Good examples for this niche: {title_examples}
- FORBIDDEN: "The/A [noun] of [thing]", "Protocol of...", "Heritage of..."

=== IMAGE RULES (FOR AI IMAGE GENERATION) ===
- Choose between 4 and 8 images based on story length
- Each image MUST have a TIMESTAMP in format MM:SS
- PACING: ~135 words per minute of narration
- DISTRIBUTION: visual hook (0:00), development, climax, close
- Minimum 6 seconds between images
- Prompts in ENGLISH, 40-70 words, SPECIFIC to scenes in THIS story
- Image style for this niche: {niche['imagen_estilo']}
- VARIETY: Do NOT repeat the same composition or perspective

=== OUTPUT FORMAT (EXACT — do not copy instructions, just fill in) ===

===STORY 1===
IMAGES: [number]

[Your title here]

[Full story — remember the mandatory length]

===IMAGES 1===
IMG1 0:00: [detailed prompt of the hook scene, visual style, composition]
IMG2 0:12: [detailed prompt of the development scene, different composition]
IMG3 0:25: [detailed prompt of the climax scene]
IMG4 0:40: [detailed prompt of the close/twist scene]

===SFX 1===
0:12: rain
0:25: heartbeat
0:40: door_knocking

START DIRECTLY with ===STORY 1===, no preamble or explanations."""

    # ── Call the active model via stream() ────────────────────────────────────
    internal_config = dict(config)
    internal_config.update({"max_tokens": 5000, "temperature": 0.95, "stream": True})

    chunks: list[str] = []
    try:
        for event in stream(model, "You are a viral content writer.", [{"role": "user", "content": prompt}], [], internal_config):
            if isinstance(event, TextChunk):
                chunks.append(event.text)
    except Exception as exc:
        print(f"  Story generation error: {exc}")
        return None

    response = "".join(chunks).strip()
    if not response:
        return None

    result = _parse_story_response(response, niche_id, niche)

    # If story is too short (model didn't follow structured format), try simpler prompt
    if result is None or _story_too_short(result):
        _diag = f"{len(result['story'].split())} words" if result else "parse failed"
        print(f"  Story too short ({_diag}) — retrying with simplified prompt...")
        result = _retry_simple(topic, model, niche_id, niche, target_words, is_short, lang_instr, internal_config)

    # Final fallback: completely free-form, no format required
    if result is None or _story_too_short(result):
        _diag = f"{len(result['story'].split())} words" if result else "still failed"
        print(f"  Simplified retry too short ({_diag}) — using free-form fallback...")
        result = _retry_freeform(topic, model, niche_id, niche, target_words, is_short, lang_instr, internal_config)

    return result


def _story_too_short(result: dict) -> bool:
    story = result.get('story', '')
    char_count = len(story)
    word_count = len(story.split())
    # CJK scripts have no spaces — use char count as primary metric
    # 150 chars ≈ 100 Chinese characters ≈ a meaningful paragraph
    if char_count >= 150:
        return False
    # For Latin scripts, also check word count
    return word_count < 40


def _stream_text(model, system, prompt, config) -> str:
    """Helper: stream a model call and return the full response string."""
    from providers import stream, TextChunk  # type: ignore
    chunks: list[str] = []
    try:
        for event in stream(model, system, [{"role": "user", "content": prompt}], [], config):
            if isinstance(event, TextChunk):
                chunks.append(event.text)
    except Exception as exc:
        print(f"  Model call error: {exc}")
    return "".join(chunks).strip()


def _retry_simple(topic, model, niche_id, niche, target_words, is_short, lang_instr, config):
    """Retry with a minimal structured prompt."""
    lang_block = f"IMPORTANT: Write ENTIRELY in this language: {lang_instr}\n\n" if lang_instr else ""
    length_rule = (f"~{target_words} words." if target_words
                   else ("80-110 words." if is_short else "300-450 words."))
    prompt = f"""{lang_block}Write a viral short story for YouTube/TikTok.
Topic/niche: {niche['nombre']}
{('Direction: ' + topic) if topic else ''}
Length: {length_rule}
First person ("I"). Strong hook. Twist ending.

OUTPUT FORMAT — copy exactly, fill in content:
===STORY 1===
IMAGES: 4

[Title — max 8 words]

[Full story here]

===IMAGES 1===
IMG1 0:00: [scene, photorealistic style]
IMG2 0:20: [scene]
IMG3 0:40: [scene]
IMG4 1:00: [scene]

===SFX 1===
0:20: wind"""

    response = _stream_text(model, "You are a creative writer.", prompt, config)
    if not response:
        return None
    return _parse_story_response(response, niche_id, niche)


def _retry_freeform(topic, model, niche_id, niche, target_words, is_short, lang_instr, config):
    """
    Last-resort fallback: ask for plain prose with zero format requirements.
    Builds the result dict manually from raw output.
    """
    word_target = target_words or (90 if is_short else 350)
    subject     = topic or niche['nombre']
    lang_note   = f"\n{lang_instr}" if lang_instr else ""
    prompt = (f"Write a {word_target}-word first-person story about: {subject}.{lang_note}\n"
              "Strong hook. One twist. No headers, no bullet points, just the story text.")

    story_text = _stream_text(model, "You are a storyteller.", prompt, config)
    # Accept anything ≥ 30 chars — even a short story is better than nothing
    if len(story_text) < 30:
        return None

    # Derive title: first sentence or first 8 words
    first_sent = re.split(r'[.!?\n]', story_text)[0].strip()
    title = ' '.join(first_sent.split()[:8]) if first_sent else (topic or "Untitled")

    # Build evenly-spaced image prompts from story content
    num_imgs  = 4
    duration  = word_target / 135            # estimated minutes
    style     = niche.get('imagen_estilo', 'cinematic photography')
    # Extract scene-like sentences from story for prompts
    sentences = [s.strip() for s in re.split(r'[.!?]', story_text) if len(s.strip()) > 20]
    img_data  = []
    for i in range(num_imgs):
        secs    = int(i * duration * 60 / max(num_imgs - 1, 1))
        mm, ss  = divmod(secs, 60)
        ts      = f"{mm}:{ss:02d}"
        # Pick an evenly spaced sentence as context for the image
        si      = int(i * len(sentences) / num_imgs) if sentences else 0
        base    = sentences[si] if si < len(sentences) else subject
        img_data.append({'prompt': f"{base[:80]}, {style}", 'timestamp': ts, 'seconds': secs})

    print(f"  Free-form fallback: {len(story_text.split())} words, {num_imgs} images")
    return {
        'title':          title,
        'story':          story_text,
        'niche_id':       niche_id,
        'niche':          niche,
        'image_prompts':  img_data,
        'sfx_cues':       [],
        'has_timestamps': True,
    }


# ── Internal parser ────────────────────────────────────────────────────────────

def _parse_story_response(response: str, niche_id: str, niche: dict) -> dict | None:
    """Parse the structured response into a story dict."""
    # Split off the STORY block
    blocks = re.split(r'(?:#+\s*)?===\s*STORY\s*\d+\s*===', response, flags=re.IGNORECASE)
    blocks = [b.strip() for b in blocks if b.strip()]
    if not blocks:
        return None

    block = blocks[0]

    # Split story, images, SFX
    parts = re.split(r'(?:#+\s*)?===\s*(?:IMAGES?|SFX)\s*\d+\s*===', block, flags=re.IGNORECASE)
    story_part   = parts[0].strip()
    images_part  = parts[1].strip() if len(parts) > 1 else ""
    sfx_part     = parts[2].strip() if len(parts) > 2 else ""

    lines = [l.strip() for l in story_part.split('\n') if l.strip()]
    # Strip IMAGES: N metadata lines
    clean_lines = [l for l in lines if not re.match(r'IMAGES?:\s*\d+', l, re.IGNORECASE)]

    if len(clean_lines) < 2:
        return None

    # Extract title (first non-numeric, non-metadata line)
    title = None
    for line in clean_lines:
        cleaned = re.sub(r'[^\x20-\x7E\u00C0-\u024F\u1E00-\u1EFF]', '', line).strip()
        cleaned = re.sub(r'\s*[—–-]+\s*$', '', cleaned).strip()
        if len(cleaned) >= 3 and not re.match(r'^\d+$', cleaned):
            title = cleaned
            break
    if not title:
        title = "Untitled Story"

    story_text = '\n'.join(clean_lines[1:]).strip()
    # CJK text has no spaces — 30 chars minimum (a short Chinese sentence is ~15 chars)
    if len(story_text) < 30:
        return None

    # Parse image prompts
    img_data = []
    for m in re.finditer(r'IMG\d+\s+(\d+:\d+)\s*:\s*(.+?)(?=\nIMG\d+|\n===|\Z)', images_part, re.MULTILINE | re.DOTALL):
        ts = m.group(1).strip()
        prompt_text = ' '.join(m.group(2).strip().split())
        if len(prompt_text) > 15:
            img_data.append({'prompt': prompt_text, 'timestamp': ts, 'seconds': parse_timestamp(ts)})

    # Fallback: no timestamps
    if not img_data:
        for m in re.finditer(r'IMG\d+:\s*\[?(.+?)\]?\s*$', images_part, re.MULTILINE):
            p = m.group(1).strip()
            if len(p) > 15:
                img_data.append({'prompt': p, 'timestamp': None, 'seconds': None})

    # Parse SFX cues (names only — actual file lookup happens in assembly)
    sfx_cues = []
    for m in re.finditer(r'(\d+:\d+)\s*:\s*([a-zA-Z0-9_]+)', sfx_part):
        sfx_cues.append({'timestamp': m.group(1), 'seconds': parse_timestamp(m.group(1)), 'name': m.group(2)})

    return {
        'title':          title,
        'story':          story_text,
        'niche_id':       niche_id,
        'niche':          niche,
        'image_prompts':  img_data,
        'sfx_cues':       sfx_cues,
        'has_timestamps': any(img['timestamp'] for img in img_data),
    }
