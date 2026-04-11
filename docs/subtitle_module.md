# Subtitle module

The Subtitle Agent (`app/tools/subtitle_tool.py` + `app/subtitles/`) is
the pipeline stage that turns an assembled vertical video into two
deterministic artifacts:

| Artifact | Storage key | Produced by |
|---|---|---|
| `subtitle_path` | `{job_id}/subtitles.srt` | `SubtitleTool` |
| `final_path`    | `{job_id}/final.mp4`    | `SubtitleTool` (burn-in) |

It sits between `VideoAssemblyTool` and `PublishingTool`:

```
ScriptChain → VoiceTool → VisualTool → VideoAssemblyTool → SubtitleTool → PublishingTool
```

The stage intentionally avoids any speech-recognition dependency. All
timing is derived from metadata the voice stage already produces, which
keeps the module fully offline and deterministic by default.

## Pipeline contract

Input state keys (consumed):

| Key | Type | Notes |
|---|---|---|
| `job_id` | `str` | deterministic storage keys |
| `video_path` | `str` | local path to assembled MP4 (from `VideoAssemblyTool`) |
| `script` | `Script` | `hook`, `body`, `cta` are required non-empty strings |
| `audio_segments` | `list[dict]` *(optional)* | first-choice timing source |
| `audio_segments_path` | `str` *(optional)* | JSON manifest fallback |
| `audio_duration_ms` | `int` *(optional)* | enables the deterministic script-driven fallback |

Output state keys (produced):

| Key | Type | Notes |
|---|---|---|
| `subtitle_path` | `str` | storage-resolved path to the persisted `.srt` |
| `final_path`    | `str` | storage-resolved path to the burned-in MP4 |

The tool never mutates the incoming state: it returns
`{**state, "subtitle_path": ..., "final_path": ...}`.

## Architecture

```mermaid
flowchart LR
    State[PipelineState<br/>video_path + script + voice timing] --> Tool

    subgraph SubtitleTool
      Tool[SubtitleTool.run]
      Tool --> Validate[validate_state<br/>→ SubtitlePlanContext]
      Validate --> Plan[build_cues<br/>segments → segments file → script fallback]
      Plan --> Serialize[serialize_srt<br/>SubRip timestamps]
      Serialize --> SaveSrt[(Storage.save<br/>{job_id}/subtitles.srt)]
      SaveSrt --> Stage[Storage.stage_local<br/>video + srt]
      Stage --> Burn[burn_subtitles<br/>ffmpeg subtitles filter]
      Burn --> SaveMp4[(Storage.save<br/>{job_id}/final.mp4)]
    end

    Plan -.-> Cues[(SubtitleCue<br/>frozen dataclass)]
    Burn -.-> Style[FORCE_STYLE<br/>mobile-first libass]
    SaveMp4 --> Out[PipelineState<br/>+ subtitle_path<br/>+ final_path]
```

## Components

### `app/tools/subtitle_tool.py`

The only public pipeline node. A thin orchestrator that logs each
stage and delegates real work to the helpers in `app/subtitles/`:

- `subtitle.validate.start` / `subtitle.validate.end`
- `subtitle.plan.ready` (with `cue_count`)
- `subtitle.persist.srt`
- `subtitle.burn.start` / `subtitle.burn.end`
- `subtitle.persist.final`

### `app/subtitles/validate.py`

- `SubtitleValidationError` — raised for every unusable input.
- `SubtitlePlanContext` — frozen dataclass that carries validated
  inputs and deterministic storage keys (`{job_id}/subtitles.srt`,
  `{job_id}/final.mp4`) to downstream helpers.
- `validate_state(state)` — rejects missing `job_id`, missing or
  non-existent `video_path`, missing/empty `script` sections, malformed
  `audio_segments`, and the fully-absent timing case.

### `app/subtitles/cues.py`

- `SubtitleCue` — frozen dataclass (`index`, `start_ms`, `end_ms`,
  `lines`). Integer milliseconds only, so rounding is explicit.
- `build_cues(ctx)` — public entrypoint applying the timing priority:
    1. in-memory `audio_segments`
    2. persisted `audio_segments_path`
    3. deterministic script-driven fallback
- `plan_cues_from_segments` — splits long segment text into
  mobile-readable cards (≤ 2 lines × ≤ 32 chars), distributing the
  parent segment duration proportionally using largest-remainder
  allocation so the sub-cues sum exactly to the parent.
- `plan_cues_from_script_fallback` — used when no voice metadata is
  available. Splits `hook` / `body` / `cta` into cards and allocates
  `audio_duration_ms` (or 2 s per card when silent) proportionally to
  text length.

### `app/subtitles/srt.py`

- `format_timestamp(ms)` — `HH:MM:SS,mmm` per the SubRip spec.
- `serialize_srt(cues)` — deterministic UTF-8 output with contiguous
  `1..N` cue numbering, blank-line separators between blocks, and
  newline-joined multi-line cues.

### `app/subtitles/burn.py`

- `FORCE_STYLE` — centralized libass style string. Mobile-first
  defaults: DejaVu Sans, `Fontsize=18`, boxed background
  (`BorderStyle=3`), bottom-center alignment with `MarginV=220` so the
  card sits above Shorts/TikTok UI zones.
- `burn_subtitles(video, srt, output)` — wraps one ffmpeg invocation
  using the `subtitles` filter. Inputs are staged into a
  `TemporaryDirectory` first so the filter argument always references
  simple short filenames. Audio is stream-copied (`-c:a copy`), never
  re-encoded, so narration timing is preserved byte-for-byte.

### `app/services/storage.py` (extended)

- `StagedAsset` — dataclass exposing a `local_path` and an optional
  `cleanup()` hook. Works as a context manager.
- `Storage.stage_local(key_or_path)` — new abstract method.
    - `LocalStorage` returns a passthrough `StagedAsset` (no copy).
    - `S3Storage` downloads the key into a `tempfile.mkdtemp()`
      directory, preserving the asset's extension so ffmpeg picks the
      right demuxer. `cleanup()` removes the temp dir.

This keeps the burn-in compatible with both `STORAGE_BACKEND=local` and
`STORAGE_BACKEND=s3` without leaking S3 path parsing into the subtitle
stage.

## Design decisions

- **Voice metadata is the source of timing truth.** ASR would pull in a
  large model dependency and break the degraded-mode guarantee. Cue
  timing is derived from `audio_segments` by construction, with a
  deterministic fallback when segments are absent.
- **Segment envelope preservation.** Long narration chunks are split
  for readability, but the sub-cues always sum to the parent segment
  duration (largest-remainder allocation). Two runs of the same state
  produce the same cue list.
- **One centralized style.** `FORCE_STYLE` is a single string. Adding
  configurable styling later does not require touching cue planning or
  serialization — the plan's question 2.
- **Never re-encode audio.** `burn_subtitles` passes `-c:a copy`. Voice
  timing stays byte-identical to the `VoiceTool` output.
- **Local staging for ffmpeg.** Burn-in always runs against local paths
  inside a `TemporaryDirectory`. Remote backends materialize through
  `Storage.stage_local`, not through per-tool path parsing.
- **Deterministic storage keys.** `subtitles.srt` and `final.mp4` under
  `{job_id}/`. Re-running a job overwrites in place.
- **No state mutation.** `SubtitleTool.run` returns
  `{**state, "subtitle_path": ..., "final_path": ...}`.
- **No `tempfile.mktemp`.** Replaced by `TemporaryDirectory` everywhere
  per Python stdlib guidance.

## Usage

### Inside the pipeline

```python
from app.tools.subtitle_tool import SubtitleTool

new_state = SubtitleTool().invoke(state)
# new_state["subtitle_path"] → "<storage>/{job_id}/subtitles.srt"
# new_state["final_path"]    → "<storage>/{job_id}/final.mp4"
```

### Direct invocation with hand-built state

```python
state = {
    "job_id": "demo",
    "video_path": "/tmp/assembled.mp4",
    "script": {
        "title": "Why typing matters",
        "hook": "Types catch bugs you would never see in tests.",
        "body": "Static types document intent. They help refactors.",
        "cta": "Follow for more Python tips.",
        "tags": ["python"],
    },
    "audio_duration_ms": 6000,
    "audio_segments": [
        {"section": "hook", "chunk_index": 0, "text": "Types catch bugs.", "duration_ms": 2000},
        {"section": "body", "chunk_index": 0, "text": "Static types document intent.", "duration_ms": 3000},
        {"section": "cta",  "chunk_index": 0, "text": "Follow for more.",  "duration_ms": 1000},
    ],
}
result = SubtitleTool().invoke(state)
```

### Runnable demo

A fully offline example is provided. It generates an assembled-looking
demo video with ffmpeg and invokes the tool against hand-crafted
deterministic segments:

```bash
python examples/subtitle_tool_example.py
```

Requires only `ffmpeg` on the `PATH`. No API keys, no network.

## Error handling

`validate_state` raises `SubtitleValidationError` (a `ValueError`
subclass) with a precise message for each failure mode:

- `job_id is missing or empty`
- `video_path is missing or empty`
- `video_path does not exist: <path>`
- `script is missing or not a dict`
- `script['hook'|'body'|'cta'] is missing or empty`
- `audio_segments[<i>] missing non-empty 'text'`
- `audio_segments[<i>].duration_ms must be a non-negative number`
- `no timing metadata available: need audio_segments, audio_segments_path, or audio_duration_ms`

ffmpeg failures propagate through `subprocess.CalledProcessError` with
`stderr` captured.

## Tests

See `tests/test_subtitle_tool.py`. The suite covers:

- every validation branch
- segment-driven cue planning (exact, missing durations, degraded)
- script-driven deterministic fallback
- line breaking, card splitting, punctuation-aware chunking
- proportional duration allocation
- `.srt` serialization (timestamps, indices, multi-line, determinism)
- ffmpeg command construction and filter-argument escaping
- `LocalStorage.stage_local` passthrough
- `StagedAsset` cleanup for S3-style temp dirs
- `SubtitleTool` orchestration (happy path, idempotency, degraded mode,
  state immutability, `-c:a copy` preservation)
- offline ffmpeg integration with generated stub media
