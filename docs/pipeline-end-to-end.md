# 🎥 Automated YouTube Shorts Pipeline (End-to-End)

## Overview

This document describes the complete pipeline for generating and publishing YouTube Shorts using an automated AI system. The pipeline transforms a simple input (topic) into a fully published short-form video.

---

## 🧩 High-Level Pipeline

```text
[Topic Input]
      ↓
[Script Generation]
      ↓
[Voice Generation (TTS)]
      ↓
[Visual Generation]
      ↓
[Video Assembly]
      ↓
[Subtitle Generation]
      ↓
[Publishing]
      ↓
[Analytics / Feedback Loop]
```

---

## 🔹 1. Topic Input

### Input
- Simple topic (string)

### Example
```json
{
  "topic": "AI will replace jobs"
}
```

### Output
- Normalized topic object

---

## 🔹 2. Script Generation (LangChain)

### Input
- topic

### Process
- Prompt templating
- LLM generation (hook, body, CTA)
- Structured parsing (JSON)

### Output
```json
{
  "hook": "This job will disappear in 2 years...",
  "body": "AI is already replacing...",
  "cta": "Follow for more AI insights",
  "visual_cues": ["office worker", "robot automation"]
}
```

---

## 🔹 3. Voice Generation (TTS)

### Input
- structured script

### Process
- Concatenate script
- TTS generation
- Optional timing extraction

### Output
```json
{
  "audio_path": "voice.mp3",
  "duration": 18.5
}
```

---

## 🔹 4. Visual Generation (Visual Agent)

### Input
- script + optional visual cues

### Process
- Generate prompts per segment
- Fetch/generate visuals (stock or AI)
- Normalize format (9:16)

### Output
```json
{
  "assets": [
    {"path": "img1.jpg", "duration": 3},
    {"path": "clip1.mp4", "duration": 5}
  ]
}
```

---

## 🔹 5. Video Assembly (ffmpeg)

### Input
- audio + visual assets

### Process
- Resize visuals (9:16)
- Sequence visuals
- Sync with audio
- Generate video

### Output
```json
{
  "video_path": "video.mp4"
}
```

---

## 🔹 6. Subtitle Generation

### Input
- script or audio

### Process
- Generate captions
- Timing alignment
- Burn subtitles into video

### Output
```json
{
  "video_with_subtitles": "video_final.mp4"
}
```

---

## 🔹 7. Publishing (YouTube Shorts)

### Input
- final video

### Process
- Upload via YouTube API
- Add metadata (title, description, tags)

### Output
```json
{
  "youtube_url": "https://youtube.com/shorts/..."
}
```

---

## 🔹 8. Analytics / Feedback Loop

### Input
- published video

### Process
- Fetch metrics (views, watch time, CTR)
- Identify best-performing videos
- Feed insights back into Script Generation

### Output
```json
{
  "views": 12000,
  "watch_time": 85,
  "ctr": 0.12
}
```

---

## 🧠 Data Flow Summary

```text
topic
  ↓
script.json
  ↓
voice.mp3
  ↓
visual_assets/
  ↓
video.mp4
  ↓
video_final.mp4
  ↓
published_url
  ↓
analytics.json
```

---

## 🏗️ System Design Notes

- Each stage is modular and independently testable
- Clear input/output contracts between components
- Designed for async execution (Celery)
- Compatible with LangChain / MAS architecture
- Easily extensible (multi-platform, new agents)

---

## 🚀 Next Steps

- Implement each module incrementally
- Start with Script + Voice (MVP)
- Add Visual + Assembly
- Integrate Publishing
- Add feedback loop for optimization