---
name: video
version: 1.0.0
description: AI-powered viral video content factory — story → voice → images → MP4
author: little-coder
tags: [video, tts, ai, content-creation]
commands:
  - video.cmd
dependencies:
  - edge-tts
  - Pillow
homepage: ""
---

# Video Plugin

AI video content factory with a step-by-step interactive wizard.

## Commands

- `/video [topic]` — Launch the interactive wizard
- `/video status`  — Show dependency status

## Optional dependencies

| Package          | Feature                    |
|------------------|----------------------------|
| `edge-tts`       | Free TTS (fallback voice)  |
| `faster-whisper` | Auto subtitle transcription|
| `playwright`     | Gemini Web image generation|
| `Pillow`         | Image processing           |
| `ffmpeg` (system)| Video assembly             |

## Zero-cost path

Edge TTS (free) + web image search (free) → complete MP4, no API keys needed.
