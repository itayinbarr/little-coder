---
name: voice
version: 1.0.0
description: Voice input module — record microphone → speech-to-text → submit as message
author: little-coder
tags: [voice, stt, audio, input]
commands:
  - modular.voice.cmd
dependencies:
  - sounddevice
  - faster-whisper
homepage: ""
---

# Voice Module

Record audio from microphone, transcribe via Whisper STT, and submit as a chat message.

## Commands

- `/voice`               — record and submit
- `/voice status`        — show backend availability
- `/voice lang <code>`   — set STT language (zh, en, ja, auto…)
- `/voice device`        — list and select microphone

## Dependencies

| Package          | Feature                    |
|------------------|----------------------------|
| `sounddevice`    | Microphone recording       |
| `faster-whisper` | Local STT (offline)        |

## Environment

- `NANO_CLAUDE_WHISPER_MODEL` — Whisper model size (default: `base`)
