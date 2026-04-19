"""
Image generation backends for the video pipeline.

Backends (tried in order based on availability):
  1. Gemini Web   — Playwright browser automation (100% free, Imagen 3)
     Looks for gemini_image_gen.py in the sibling v-content-creator project
     OR uses a standalone Playwright implementation.
  2. Web Search   — Downloads free stock photos from Unsplash/Pexels (no API key)
  3. Placeholder  — solid-color gradient slides (always available, no deps)
"""

import os
import sys
import re
import urllib.request
import urllib.parse


# ── Gemini Web (Playwright) ───────────────────────────────────────────────────

def _find_gemini_image_gen() -> str | None:
    """Try to locate gemini_image_gen.py from the sibling v-content-creator project."""
    # The little-coder package lives at: .../little-coder_versions/little-coder/video/
    # v-content-creator lives at:         .../little-coder_versions/v-content-creator/
    this_dir     = os.path.dirname(os.path.abspath(__file__))
    pkg_root     = os.path.dirname(this_dir)          # .../little-coder
    versions_dir = os.path.dirname(pkg_root)           # .../little-coder_versions
    candidate    = os.path.join(versions_dir, "v-content-creator", "gemini_image_gen.py")
    if os.path.isfile(candidate):
        return os.path.dirname(candidate)
    return None


def generate_images_gemini_web(prompts: list[dict], output_dir: str, is_short: bool = False) -> int:
    """
    Generate images via Gemini Web (Playwright).
    prompts: list of {'prompt': str, ...}
    Returns number of images successfully generated.
    """
    sibling_dir = _find_gemini_image_gen()
    if sibling_dir is None:
        print("  Gemini Web: gemini_image_gen.py not found in sibling v-content-creator project.")
        return 0

    if sibling_dir not in sys.path:
        sys.path.insert(0, sibling_dir)

    try:
        from gemini_image_gen import generate_images_batch, check_gemini_login  # type: ignore

        # Check login
        pw_profile = os.path.join(os.path.expanduser("~"), ".playwright-youtube")
        needs_login = not os.path.isdir(pw_profile) or not os.listdir(pw_profile)
        if needs_login:
            print("  Gemini Web: first run — need to log in.")
            print("  Run: python -c \"from gemini_image_gen import verify_login_interactive; verify_login_interactive()\"")
            print("  from the v-content-creator directory, then retry /video.")
            return 0

        prompts_data = [{'prompt': p['prompt'], 'timestamp': p.get('timestamp')} for p in prompts]
        count = generate_images_batch(prompts_data, output_dir=output_dir, is_short=is_short)
        return count
    except Exception as exc:
        print(f"  Gemini Web image error: {exc}")
        return 0


# ── Web image search (Unsplash / Pexels) ─────────────────────────────────────

def _extract_keywords(prompt: str, max_words: int = 4) -> str:
    """Extract the most relevant keywords from an image prompt for web search."""
    # Remove style/quality descriptors, keep concrete nouns/adjectives
    stop = {'a', 'an', 'the', 'of', 'in', 'at', 'on', 'and', 'or', 'with',
            'style', 'composition', 'detailed', 'high', 'quality', 'resolution',
            'cinematic', 'dramatic', 'lighting', 'photorealistic', 'ultra', 'wide',
            'close', 'shot', 'view', 'angle', 'perspective', 'scene', 'render',
            'image', 'photo', 'picture', 'showing', 'depicting', 'featuring',
            'background', 'foreground', 'blurred', 'bokeh', 'sharp', 'soft'}
    words = re.findall(r'[a-zA-Z]+', prompt.lower())
    filtered = [w for w in words if len(w) > 3 and w not in stop]
    return '+'.join(filtered[:max_words]) if filtered else 'nature+landscape'


def _download_image(url: str, out_path: str, timeout: int = 20) -> bool:
    """Download an image from URL to out_path. Returns True on success."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if len(data) < 5000:   # too small → likely an error page
            return False
        with open(out_path, 'wb') as f:
            f.write(data)
        return True
    except Exception:
        return False


def _picsum_url(width: int, height: int, seed: int) -> str:
    """Lorem Picsum — reliable free random photos, no API key."""
    return f"https://picsum.photos/seed/{seed}/{width}/{height}"


def _wikimedia_search(keywords: str, story_context: str = "") -> str | None:
    """Search Wikimedia Commons and return the most relevant image URL."""
    import json
    query = urllib.parse.quote(keywords.replace('+', ' '))
    api = (
        "https://commons.wikimedia.org/w/api.php"
        f"?action=query&generator=search&gsrsearch=File%3A{query}"
        "&prop=imageinfo&iiprop=url|extmetadata&iilimit=1&gsrlimit=8&format=json"
    )
    try:
        req = urllib.request.Request(api, headers={'User-Agent': 'little-coder/1.0'})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read())
        pages = data.get('query', {}).get('pages', {})
        candidates = []
        for page in pages.values():
            ii = page.get('imageinfo', [{}])
            url = ii[0].get('url', '')
            if url and any(url.lower().endswith(ext) for ext in ('.jpg', '.jpeg', '.png', '.webp')):
                title = page.get('title', '').lower()
                candidates.append((url, title))
        if not candidates:
            return None
        # Pick candidate whose title best matches story context
        if story_context and len(candidates) > 1:
            ctx_words = set(re.findall(r'[a-z]+', story_context.lower()))
            def score(c: tuple) -> int:
                title_words = set(re.findall(r'[a-z]+', c[1]))
                return len(ctx_words & title_words)
            candidates.sort(key=score, reverse=True)
        return candidates[0][0]
    except Exception:
        pass
    return None


def _pexels_search(keywords: str, width: int, height: int, api_key: str,
                   story_context: str = "") -> str | None:
    """Search Pexels and return the best-matching image URL."""
    import json
    query = urllib.parse.quote(keywords.replace('+', ' '))
    orient = 'portrait' if height > width else 'landscape'
    url = f"https://api.pexels.com/v1/search?query={query}&per_page=5&orientation={orient}"
    try:
        req = urllib.request.Request(url, headers={'Authorization': api_key})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        photos = data.get('photos', [])
        if not photos:
            return None
        # Pick the photo whose alt text best matches the story context
        if story_context and len(photos) > 1:
            ctx_words = set(re.findall(r'[a-z]+', story_context.lower()))
            def score(p: dict) -> int:
                alt = re.findall(r'[a-z]+', (p.get('alt') or '').lower())
                return len(ctx_words & set(alt))
            photos.sort(key=score, reverse=True)
        src = photos[0].get('src', {})
        return src.get('large2x') or src.get('large') or src.get('original')
    except Exception:
        return None


def _unsplash_search(keywords: str, width: int, height: int, access_key: str) -> str | None:
    """Search Unsplash via API (requires UNSPLASH_ACCESS_KEY env var)."""
    import json
    query = urllib.parse.quote(keywords.replace('+', ' '))
    orient = 'portrait' if height > width else 'landscape'
    url = (f"https://api.unsplash.com/search/photos"
           f"?query={query}&per_page=1&orientation={orient}&client_id={access_key}")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'little-coder/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        results = data.get('results', [])
        if not results:
            return None
        urls = results[0].get('urls', {})
        return urls.get('full') or urls.get('regular')
    except Exception:
        return None


def _ai_search_query(image_prompt: str, story_context: str,
                     model: str, config: dict) -> str:
    """
    Ask the model to generate an ideal stock photo search query
    for a specific scene, given the full story context.
    Returns '+'-joined keywords, or "" on failure.
    """
    try:
        from providers import stream, TextChunk  # type: ignore
        prompt = (
            f"Story context: {story_context[:300]}\n"
            f"Scene to illustrate: {image_prompt[:200]}\n\n"
            "Write a 3-5 word search query to find the perfect stock photo for this scene. "
            "Output ONLY the keywords separated by spaces, nothing else."
        )
        cfg = {**config, "max_tokens": 20, "temperature": 0.2, "stream": True}
        parts: list[str] = []
        for ev in stream(model, "You generate stock photo search queries.",
                         [{"role": "user", "content": prompt}], [], cfg):
            if isinstance(ev, TextChunk):
                parts.append(ev.text)
        result = "".join(parts).strip().lower().split('\n')[0]
        words = re.findall(r'[a-zA-Z]+', result)[:5]
        return '+'.join(words) if words else ""
    except Exception:
        return ""


def generate_images_web_search(prompts: list[dict], output_dir: str,
                               is_short: bool = False,
                               story_context: str = "",
                               model: str | None = None,
                               config: dict | None = None) -> int:
    """
    Download free stock photos for each prompt.

    Priority:
      1. Pexels API   (keyword search, requires PEXELS_API_KEY)
      2. Unsplash API (keyword search, requires UNSPLASH_ACCESS_KEY)
      3. Wikimedia Commons (keyword search, no API key)
      4. Lorem Picsum (random high-quality photos, no API key, always works)

    When model + config are provided, AI-generates optimal search queries.
    Returns number of images successfully downloaded.
    """
    os.makedirs(output_dir, exist_ok=True)
    w, h = (1080, 1920) if is_short else (1920, 1080)
    pexels_key   = os.getenv("PEXELS_API_KEY", "")
    unsplash_key = os.getenv("UNSPLASH_ACCESS_KEY", "")
    use_ai_query = bool(model and config and story_context)
    count = 0

    print(f"  Web search images: downloading {len(prompts)} image(s)"
          f"{' (AI queries)' if use_ai_query else ''}...")
    for i, p in enumerate(prompts):
        out_path    = os.path.join(output_dir, f"img_{i:02d}.jpg")
        raw_prompt  = p.get('prompt', f'scene {i+1}')

        # AI-generated query or mechanical extraction
        if use_ai_query:
            ai_kw = _ai_search_query(raw_prompt, story_context, model, config)  # type: ignore
            keywords = ai_kw if ai_kw else _extract_keywords(raw_prompt)
        else:
            keywords = _extract_keywords(raw_prompt)

        print(f"    [{i+1}/{len(prompts)}] {keywords.replace('+', ' ')}")
        downloaded = False

        # 1. Pexels (keyword, API key)
        if pexels_key and not downloaded:
            img_url = _pexels_search(keywords, w, h, pexels_key, story_context)
            if img_url:
                downloaded = _download_image(img_url, out_path)

        # 2. Unsplash API (keyword, API key)
        if unsplash_key and not downloaded:
            img_url = _unsplash_search(keywords, w, h, unsplash_key)
            if img_url:
                downloaded = _download_image(img_url, out_path)

        # 3. Wikimedia Commons (keyword, no API key)
        if not downloaded:
            img_url = _wikimedia_search(keywords, story_context)
            if img_url:
                downloaded = _download_image(img_url, out_path, timeout=20)

        # 4. Lorem Picsum (random, no API key — always reliable)
        if not downloaded:
            url = _picsum_url(w, h, seed=hash(keywords) % 1000)
            downloaded = _download_image(url, out_path, timeout=20)

        if downloaded:
            count += 1
        else:
            print(f"    [{i+1}] download failed")

    print(f"  Web search: {count}/{len(prompts)} image(s) downloaded")
    return count


# ── Placeholder images ────────────────────────────────────────────────────────

_GRADIENT_PALETTES = [
    [(15, 15, 40), (40, 20, 80)],    # deep purple
    [(20, 5, 5),   (80, 20, 20)],    # dark red
    [(5, 20, 40),  (10, 60, 100)],   # ocean blue
    [(5, 30, 10),  (20, 80, 30)],    # forest green
    [(40, 20, 5),  (100, 60, 10)],   # amber
    [(10, 10, 30), (50, 30, 80)],    # indigo
    [(30, 5, 20),  (80, 15, 50)],    # magenta dark
    [(5, 30, 30),  (15, 80, 80)],    # teal
]


def _make_placeholder(width: int, height: int, palette_idx: int, label: str, out_path: str) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont
        c1, c2 = _GRADIENT_PALETTES[palette_idx % len(_GRADIENT_PALETTES)]
        img = Image.new("RGB", (width, height))
        pixels = img.load()
        for y in range(height):
            t = y / height
            r = int(c1[0] + (c2[0] - c1[0]) * t)
            g = int(c1[1] + (c2[1] - c1[1]) * t)
            b = int(c1[2] + (c2[2] - c1[2]) * t)
            for x in range(width):
                pixels[x, y] = (r, g, b)  # type: ignore
        draw = ImageDraw.Draw(img)
        # Wrap label text
        max_w = width - 80
        words = label.split()
        lines: list[str] = []
        line = ""
        for word in words:
            test = (line + " " + word).strip()
            if len(test) * 14 > max_w and line:
                lines.append(line)
                line = word
            else:
                line = test
        if line:
            lines.append(line)
        font_size = 32
        lh = font_size + 8
        total_h = len(lines) * lh
        y0 = (height - total_h) // 2
        for i, l in enumerate(lines):
            # estimate text width
            tw = len(l) * (font_size // 2)
            x0 = (width - tw) // 2
            # shadow
            draw.text((x0 + 2, y0 + i * lh + 2), l, fill=(0, 0, 0, 128))
            draw.text((x0, y0 + i * lh), l, fill=(220, 220, 220))
        img.save(out_path, quality=95)
        return True
    except ImportError:
        # Pillow not available — create a minimal valid PNG via raw bytes
        return _make_minimal_png(width, height, out_path)
    except Exception as exc:
        print(f"  Placeholder image error: {exc}")
        return _make_minimal_png(width, height, out_path)


def _make_minimal_png(width: int, height: int, out_path: str) -> bool:
    """Create a tiny black PNG without Pillow using raw PNG bytes."""
    import zlib, struct as _struct

    def png_chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return _struct.pack('>I', len(data)) + tag + data + _struct.pack('>I', crc)

    w, h = 4, 4  # tiny placeholder
    raw = b''.join(b'\x00' + b'\x00\x00\x00' * w for _ in range(h))
    compressed = zlib.compress(raw)
    png = (
        b'\x89PNG\r\n\x1a\n'
        + png_chunk(b'IHDR', _struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
        + png_chunk(b'IDAT', compressed)
        + png_chunk(b'IEND', b'')
    )
    try:
        with open(out_path, 'wb') as f:
            f.write(png)
        return True
    except OSError:
        return False


def generate_images_placeholder(prompts: list[dict], output_dir: str, is_short: bool = False) -> int:
    """Generate solid-color gradient placeholder images for each prompt."""
    os.makedirs(output_dir, exist_ok=True)
    w, h = (1080, 1920) if is_short else (1920, 1080)
    count = 0
    for i, p in enumerate(prompts):
        out_path = os.path.join(output_dir, f"img_{i:02d}.png")
        label = p.get('prompt', '')[:120]
        if _make_placeholder(w, h, i, label, out_path):
            count += 1
    print(f"  Placeholder images: {count}/{len(prompts)}")
    return count


# ── Unified entry point ───────────────────────────────────────────────────────

def generate_images(prompts: list[dict], output_dir: str,
                    engine: str = "auto",
                    is_short: bool = False,
                    story_context: str = "",
                    model: str | None = None,
                    config: dict | None = None) -> int:
    """
    Generate images for video.

    engine: "auto" | "gemini-web" | "web-search" | "placeholder"
    - "auto": try gemini-web → web-search → placeholder
    story_context: story title + text, used for AI query generation and relevance scoring
    model / config: when provided, enables AI-generated search queries
    Returns number of images generated.
    """
    os.makedirs(output_dir, exist_ok=True)

    if engine in ("gemini-web", "auto"):
        count = generate_images_gemini_web(prompts, output_dir, is_short)
        if count > 0:
            return count
        if engine == "gemini-web":
            return 0

    if engine in ("web-search", "auto"):
        count = generate_images_web_search(
            prompts, output_dir, is_short,
            story_context=story_context, model=model, config=config,
        )
        if count > 0:
            return count
        # Web search failed — always fall through to placeholder rather than blocking pipeline
        if engine == "web-search":
            print("  Web search failed — falling back to placeholder images.")

    return generate_images_placeholder(prompts, output_dir, is_short)
