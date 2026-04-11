# Subtitle Generation Analysis

## 1. Description of the problem

The next pipeline stage to implement is `SubtitleTool`. Its job is to consume the assembled video produced by
`VideoAssemblyTool` and generate:

- a deterministic subtitle file at `subtitle_path`
- a final video with burned-in captions at `final_path`

From `AGENTS.md`, `README.md`, and the current codebase, the stage must respect these project constraints:

- it must be a `PipelineTool` and return a new `PipelineState` without mutating the input
- it must work in degraded mode, including silent audio and no external API keys
- it must persist outputs through `app.services.storage.get_storage()`
- it must rely on `ffmpeg` via `subprocess.run(..., check=True, capture_output=True)` and never `shell=True`
- it must keep deterministic storage keys based on `job_id`

Current state:

- `app/tools/subtitle_tool.py` is only a naive stub
- it ignores `audio_segments` and `audio_duration_ms`
- it splits `script["body"]` on `". "` and assigns every line a fixed 3-second duration
- it burns subtitles directly with a simple `subtitles=...:force_style=...` filter

That implementation is enough as a placeholder, but not enough for a production-ready pipeline because it does not align
captions with the voice timeline and does not explicitly handle degraded mode, S3-backed storage, cue readability, or
validation.

## 2. Research summary

Official sources reviewed:

- FFmpeg filters documentation: https://ffmpeg.org/ffmpeg-filters.html
- OpenAI Whisper repository: https://github.com/openai/whisper

Key findings:

- FFmpeg `subtitles` draws subtitles over video using `libass`, accepts a subtitle filename, and supports options such
  as `force_style`, `fontsdir`, `original_size`, and `wrap_unicode`. This is the most direct path for burning `.srt`
  subtitles into the final MP4.
- FFmpeg `ass` is similar to `subtitles` but is limited to ASS files and is better suited to advanced subtitle styling
  and layout control.
- FFmpeg `drawtext` can draw text from a literal string or a UTF-8 `textfile`, and supports box, border, alignment, line
  spacing, and file reload. It is flexible, but it pushes more timing and escaping complexity into the filtergraph.
- Whisper can transcribe audio from the command line or from Python. It is a real ASR/transcription path, but it
  introduces a model/runtime dependency and shifts the subtitle stage from deterministic cue generation to speech
  recognition.

Implications for this project:

- The repo already has deterministic narration metadata in `audio_segments`, where each segment includes `section`,
  `chunk_index`, `text`, and `duration_ms`.
- That makes it unnecessary to depend on external transcription for the default implementation.
- File-based subtitles are a better fit than raw timed `drawtext` overlays because the pipeline contract already expects
  a subtitle artifact (`subtitle_path`), not just a visual effect.
- If the project later wants richer styling, ASS is a valid extension, but it is not required for the first solid
  implementation.

## 3. Thinking process

The cleanest approach is to treat subtitle generation as a two-part problem:

1. Build a canonical list of subtitle cues.
2. Render those cues into both a stored subtitle artifact and a burned-in final MP4.

The most important design choice is the source of timing truth. In this codebase, the best timing source is:

- first choice: `audio_segments`
- second choice: `audio_segments_path`
- fallback: deterministic reconstruction from `script` plus `audio_duration_ms`

This ordering matches the project architecture:

- `VoiceTool` already produces narration chunk metadata
- degraded mode still needs to work without any online service
- `SubtitleTool` should consume existing pipeline state instead of rebuilding knowledge from audio when not necessary

The design should also separate concerns internally even if the public pipeline node remains a single `SubtitleTool`:

- cue planning: convert voice/script data into readable subtitle cues
- serialization: export cues to `.srt`
- burn-in: call `ffmpeg` to render captions onto `video_path`
- validation: verify subtitle and final video artifacts before updating state

## 4. Solutions

### Solution 1. Segment-driven SRT generation + FFmpeg `subtitles` burn-in

#### Description

Use `audio_segments` as the primary timing source. Build subtitle cues by accumulating segment durations, optionally
splitting long segment text into smaller readable lines while preserving the parent segment timing. Export `.srt`, then
burn it into `video_path` using the FFmpeg `subtitles` filter with a controlled `force_style`.

This is the most direct fit for the current pipeline contract because:

- inputs already exist in `PipelineState`
- output explicitly includes `subtitle_path`
- it works without any external model or API
- it is deterministic and testable

Expected flow:

1. Validate `video_path` and resolve timing metadata.
2. Build subtitle cues from `audio_segments`.
3. If a segment is too long for one subtitle card, split it by punctuation or word count and allocate sub-durations
   proportionally.
4. Serialize cues to `job_id/subtitles.srt`.
5. Burn captions into the assembled video with `ffmpeg -vf subtitles=...`.
6. Persist `job_id/final.mp4`.
7. Return `{**state, "subtitle_path": ..., "final_path": ...}`.

#### Example

```python
segments = [
    {"section": "hook", "chunk_index": 0, "text": "This job will disappear in two years.", "duration_ms": 2400},
    {"section": "body", "chunk_index": 0, "text": "AI is already replacing repetitive office tasks.",
     "duration_ms": 3200},
    {"section": "cta", "chunk_index": 0, "text": "Follow for more AI insights.", "duration_ms": 1800},
]
```

Possible `.srt` output:

```srt
1
00:00:00,000 --> 00:00:02,400
This job will disappear
in two years.

2
00:00:02,400 --> 00:00:05,600
AI is already replacing
repetitive office tasks.

3
00:00:05,600 --> 00:00:07,400
Follow for more AI insights.
```

Possible burn-in command:

```bash
ffmpeg -y -i video.mp4 \
  -vf "subtitles=subtitles.srt:force_style='Fontname=DejaVu Serif,Fontsize=18,BorderStyle=3,Outline=1'" \
  -c:a copy final.mp4
```

### Solution 2. Deterministic cue model + FFmpeg `drawtext` overlays

#### Description

Still build cues from `audio_segments`, but instead of rendering a subtitle file as the source of the burn-in, generate
a timed `drawtext` filtergraph. Each cue is activated only during its time window using `enable='between(t,start,end)'`.
The `.srt` file is still written for `subtitle_path`, but the visual rendering path is driven by filtergraph overlays.

This gives more low-level control over placement and styling, but it is materially more complex than file-based
subtitles:

- filtergraph escaping becomes fragile
- one filter entry is needed per cue
- debugging is harder
- the implementation surface is larger for little product gain in an MVP

#### Example

Pseudo-rendering approach:

```python
cues = [
    {"start": 0.0, "end": 2.4, "text": "This job will disappear\\nin two years."},
    {"start": 2.4, "end": 5.6, "text": "AI is already replacing\\nrepetitive office tasks."},
]
```

Possible FFmpeg filtergraph:

```bash
ffmpeg -y -i video.mp4 -vf "\
drawtext=textfile=cue1.txt:enable='between(t,0.0,2.4)':x=(w-text_w)/2:y=h-320:fontsize=54:fontcolor=white:borderw=3:box=1:boxcolor=black@0.35,\
drawtext=textfile=cue2.txt:enable='between(t,2.4,5.6)':x=(w-text_w)/2:y=h-320:fontsize=54:fontcolor=white:borderw=3:box=1:boxcolor=black@0.35" \
  -c:a copy final.mp4
```

### Solution 3. Audio transcription/alignment with Whisper + subtitle export

#### Description

Use `audio_path` as the primary source of truth and run Whisper to transcribe the narration, then export `.srt` and burn
captions into the video. The script can be used as a reference for normalization or correction, but the timings come
from ASR output rather than from `audio_segments`.

This is attractive if the pipeline must reflect the exact spoken waveform rather than the intended script, but it is a
weaker fit for the current project phase because:

- it adds a heavyweight model/runtime dependency
- it is slower
- it complicates local and CI setup
- it is less aligned with the project's deterministic degraded mode

It becomes more compelling only if the voice stage starts producing audio that diverges materially from the provided
segment text.

#### Example

Possible transcription flow:

```bash
whisper voice.mp3 --model turbo --task transcribe
```

Or in Python:

```python
import whisper

model = whisper.load_model("turbo")
result = model.transcribe("voice.mp3")
segments = result["segments"]
```

Then convert `segments` into `.srt` cues and burn them into `video_path`.

## 5. Comparison criteria & Summary Table

### Comparison criteria

- contract fit: how well the solution matches `PipelineState` and `SubtitleTool`
- determinism: how stable the output is for the same input
- degraded-mode compatibility: whether it works without external services or secrets
- implementation complexity: amount of code and edge-case handling required
- styling flexibility: how much control we get over mobile-readable presentation
- operational cost: runtime and dependency burden
- testability: ease of unit and integration testing

### Summary Table

| Solution                            | Contract fit | Determinism | Degraded mode | Implementation complexity | Styling flexibility | Operational cost | Testability |
|-------------------------------------|--------------|-------------|---------------|---------------------------|---------------------|------------------|-------------|
| 1. Segment-driven SRT + `subtitles` | Excellent    | Excellent   | Excellent     | Low                       | Medium              | Low              | Excellent   |
| 2. Cue model + `drawtext`           | Good         | Excellent   | Excellent     | High                      | High                | Medium           | Medium      |
| 3. Whisper transcription            | Medium       | Medium      | Weak          | High                      | Medium              | High             | Medium      |

### Ranked solutions

1. Solution 1. Segment-driven SRT generation + FFmpeg `subtitles` burn-in
2. Solution 2. Deterministic cue model + FFmpeg `drawtext` overlays
3. Solution 3. Audio transcription/alignment with Whisper + subtitle export

## 6. Choosen solution

Chosen solution: Solution 1. Segment-driven SRT generation + FFmpeg `subtitles` burn-in.

Why this is the best fit now:

- It uses metadata the pipeline already owns instead of introducing speech recognition.
- It satisfies the required output contract exactly: `subtitle_path` and `final_path`.
- It remains deterministic across runs for the same `job_id`, script, and voice metadata.
- It is compatible with the project's degraded-mode rule.
- It is easy to test with fixed `audio_segments` fixtures.
- It leaves a clear upgrade path for later ASS styling without forcing that complexity into the first implementation.

Recommended architecture for implementation:

- keep the public node as `app/tools/subtitle_tool.py`
- move internal logic into a dedicated `app/subtitles/` package
- suggested modules:
    - `app/subtitles/cues.py` for cue planning and line breaking
    - `app/subtitles/srt.py` for `.srt` serialization
    - `app/subtitles/burn.py` for ffmpeg command assembly and execution
    - `app/subtitles/validate.py` for state and artifact checks

Recommended behavior details:

- prefer `audio_segments` over reparsing the voice JSON file
- if a segment has missing `duration_ms`, derive fallback durations from `audio_duration_ms` and text length
- keep cue text short enough for mobile readability, usually one or two lines
- use `.srt` as the canonical persisted subtitle artifact
- if storage backend is S3, stage subtitle/video inputs to local temp paths before invoking `ffmpeg`, then persist the
  output back through storage

## 7. Notes

- The existing stub should not be extended in-place with more ad hoc logic. It is already mixing cue generation,
  serialization, and burn-in in one file.
- Subtitle timing should stay text-driven and deterministic by default, not ASR-driven.
- The stage should validate that subtitle duration does not exceed the assembled video duration in a surprising way.
- The stage should preserve the existing audio stream when burning subtitles unless there is a specific reason to
  re-encode audio.
- Tests should cover:
    - cue planning from exact `audio_segments`
    - fallback timing when segments or durations are incomplete
    - `.srt` serialization correctness
    - `ffmpeg` command construction
    - end-to-end state enrichment with `subtitle_path` and `final_path`
- If the team wants more visual polish later, an internal ASS export can be added without changing the public
  `PipelineState`.

## 8. Ask clarification on unclear topic

### Question 1

Should subtitle timing follow `audio_segments` exactly, or can one voice segment be split into multiple subtitle cues
for readability?

Answer: Split long voice segments into multiple subtitle cues for readability, but preserve the original
segment timing envelope and divide its duration proportionally.

### Question 2

Do you want `subtitle_path` to always point to a `.srt` file, even if we later generate an internal `.ass` file for
better burn-in styling?

Answer: generate `.ass` as an internal intermediate artifact only.

### Question 3

Should subtitle styling be configurable from settings now, or can we hardcode one mobile-first default style for the
first implementation?

Answer:Start with one well-chosen mobile-first default style and keep the style parameters centralized so
config support can be added later without changing the tool contract.

### Question 4

When `STORAGE_BACKEND=s3`, is it acceptable for `SubtitleTool` to stage `video_path` and subtitle files to temporary
local paths before calling `ffmpeg`?

Answer:Yes. Stage to local temp files for the `ffmpeg` run, then persist the final MP4 back through the
storage abstraction. That keeps the pipeline compatible with both local and S3 storage.
