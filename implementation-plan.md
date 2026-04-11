# Subtitle Generation Implementation Plan

## 1. Description of the problem

The next missing pipeline stage is `SubtitleTool`. In Shorts Factory, this stage sits after `VideoAssemblyTool` and
before `PublishingTool`, and it must turn an assembled vertical video into two deterministic outputs:

- `subtitle_path`: a persisted subtitle artifact
- `final_path`: a persisted MP4 with burned-in subtitles

The implementation must follow the project contract described in `AGENTS.md` and reinforced by `README.md`:

- keep the public pipeline node as a `PipelineTool`
- consume and enrich `PipelineState` without mutating it in place
- work in degraded mode with no external API keys
- use `ffmpeg` through `subprocess.run(..., check=True, capture_output=True)` only
- persist artifacts through `app.services.storage.get_storage()`
- stay deterministic and idempotent per `job_id`

The current `app/tools/subtitle_tool.py` is only a placeholder. It assigns fixed 3-second durations, ignores
`audio_segments` timing metadata, uses `tempfile.mktemp`, and mixes cue generation, serialization, and burn-in in one
file. That is enough for a prototype, but not enough for a robust pipeline stage.

Two repo-specific constraints shape the implementation:

- `VoiceTool` already produces deterministic timing metadata through `audio_segments`, `audio_segments_path`, and
  `audio_duration_ms`
- `Storage` can persist files, but today it does not expose a clean way to materialize an already-persisted asset to a
  local path when `STORAGE_BACKEND=s3`, which matters because `ffmpeg` subtitle burn-in needs local file paths

## 2. Description of the chosen solution

Chosen solution: segment-driven `.srt` generation plus FFmpeg `subtitles` burn-in.

The implementation should treat subtitle generation as four internal responsibilities behind one public `SubtitleTool`:

- validate the pipeline inputs and resolve deterministic output keys
- plan subtitle cues from existing timing metadata
- serialize those cues into `.srt`
- burn the `.srt` onto the assembled video and persist the final MP4

The timing source priority should be:

1. `audio_segments`
2. `audio_segments_path`
3. deterministic fallback from `script` and `audio_duration_ms`

This matches the architecture already present in the repo: the voice stage has already done the hard work of splitting
narration into chunks and recording per-chunk durations. Subtitle generation should reuse that information instead of
introducing speech recognition.

Research notes used for this plan:

- FFmpeg official filters documentation shows that the `subtitles` filter is designed for subtitle-file rendering and
  supports style control through options such as `force_style`, `fontsdir`, `original_size`, and `wrap_unicode`. That
  makes `.srt` the best canonical artifact for this stage while keeping burn-in simple.
- FFmpeg documentation also shows that `drawtext` is flexible but much more filtergraph-heavy and escaping-prone, which
  is why it was not chosen for the default implementation.
- Python standard-library documentation for `tempfile`, surfaced through Google search and Context7 resolution of
  `/python/cpython`, recommends `TemporaryDirectory` and `NamedTemporaryFile` for secure, automatic cleanup. That
  directly supports removing the current `tempfile.mktemp` usage.

Implementation shape recommended from `brainstorming.md`:

- keep `app/tools/subtitle_tool.py` as the single public pipeline node
- move internal logic into `app/subtitles/`
- suggested internal modules:
    - `app/subtitles/cues.py`
    - `app/subtitles/srt.py`
    - `app/subtitles/burn.py`
    - `app/subtitles/validate.py`

Additional implementation note:

- because `video_path` and generated subtitle files may need to be consumed locally by `ffmpeg`, the chosen solution
  likely requires a small storage-layer enhancement for local staging or materialization when the backend is S3

## 3. Detailed implementation plan

### Architecture and scaffolding

- [x] Replace the current monolithic subtitle stub design with a package-oriented structure by scaffolding
  `app/subtitles/__init__.py`, `app/subtitles/cues.py`, `app/subtitles/srt.py`, `app/subtitles/burn.py`, and
  `app/subtitles/validate.py`, while keeping `app/tools/subtitle_tool.py` as the single public pipeline entry point.
- [x] Run all tests and fix failing tests.
- [x] Add subtitle test scaffolding by creating a dedicated `tests/test_subtitle_tool.py` file and any shared helper
  fixtures needed to generate small local demo video/audio assets for subtitle tests.
- [x] Run all tests and fix failing tests.

### Storage and validation

- [x] Extend `app/services/storage.py` with a read-or-stage capability that can materialize an existing persisted asset
  to a local path for `ffmpeg` consumers, with a cheap passthrough path for `LocalStorage` and temporary local staging
  support for `S3Storage`.
- [x] Run all tests and fix failing tests.
- [x] Add storage-focused tests or test doubles that cover the new staging/materialization behavior required by subtitle
  rendering, especially the local path case and the S3-backed case.
- [x] Run all tests and fix failing tests.
- [x] Implement validation logic in `app/subtitles/validate.py` for `job_id`, `video_path`, `script`, timing metadata
  availability, deterministic output keys, and failure messages when the state is insufficient to build reliable
  subtitle cues.
- [x] Run all tests and fix failing tests.
- [x] Add validation tests covering missing `video_path`, missing `script`, malformed `audio_segments`, absent fallback
  timing data, and unsupported storage-materialization scenarios.
- [x] Run all tests and fix failing tests.

### Cue planning

- [x] Implement a cue model and planning logic in `app/subtitles/cues.py` that resolves timing in priority order:
  `audio_segments`, then `audio_segments_path`, then a deterministic fallback derived from `script` and
  `audio_duration_ms`.
- [x] Run all tests and fix failing tests.
- [x] Add cue-planning unit tests for exact segment timing, deterministic fallback timing, missing per-segment
  durations, and degraded-mode behavior with silent audio.
- [x] Run all tests and fix failing tests.
- [x] Implement readability rules in `app/subtitles/cues.py` so long narration chunks can be split into one or more
  subtitle cards while preserving the parent timing envelope and distributing durations proportionally.
- [x] Run all tests and fix failing tests.
- [x] Add unit tests for line breaking, proportional timing after segment splitting, punctuation-aware chunking, and
  stable cue ordering.
- [x] Run all tests and fix failing tests.

### Subtitle serialization

- [x] Implement `.srt` serialization in `app/subtitles/srt.py`, including timestamp formatting helpers, UTF-8 output,
  deterministic cue numbering, and newline handling suitable for persisted subtitle files.
- [x] Run all tests and fix failing tests.
- [x] Add serialization unit tests for timestamp formatting, cue numbering, blank-line separation, multiline cues, and
  deterministic text output.
- [x] Run all tests and fix failing tests.

### Burn-in rendering

- [x] Implement subtitle burn-in in `app/subtitles/burn.py` using local staged inputs, `TemporaryDirectory` or
  `NamedTemporaryFile` instead of `tempfile.mktemp`, and a centralized mobile-first `force_style` string for FFmpeg
  `subtitles=` rendering.
- [x] Run all tests and fix failing tests.
- [x] Add renderer tests that verify ffmpeg command construction, subtitle-file staging, audio preservation,
  temporary-file cleanup, and final artifact persistence through storage.
- [x] Run all tests and fix failing tests.
- [x] Ensure the burn-in path keeps the existing audio stream intact unless a subtitle-rendering constraint forces a
  different codec decision, and document that rule directly in the implementation through code structure and tests.
- [x] Run all tests and fix failing tests.
- [x] Add tests for duration coherence between the input `video_path`, generated `.srt`, and final MP4 so regressions in
  cue timing are caught early.
- [x] Run all tests and fix failing tests.

### Public tool orchestration

- [x] Refactor `app/tools/subtitle_tool.py` into a thin orchestrator that logs each stage, invokes
  validation/planning/serialization/rendering helpers, returns `{**state, "subtitle_path": ..., "final_path": ...}`, and
  removes legacy helpers such as `_to_srt`, `_ts`, and `tempfile.mktemp` usage.
- [x] Run all tests and fix failing tests.
- [x] Update impacted existing tests, especially `tests/test_pipeline.py`, so the pipeline smoke test reflects the full
  subtitle-stage contract rather than only a final video placeholder.
- [x] Run all tests and fix failing tests.

### Example and final verification

- [x] Create `examples/subtitle_tool_example.py` following the style of the existing demo scripts so a developer can run
  the subtitle stage offline with a prepared assembled video, a small script payload, and deterministic
  `audio_segments`.
- [x] Run all tests and fix failing tests.
- [x] Run `ruff check app/ tests/ examples/` and fix any remaining issues before considering the implementation
  complete.

## 4. Notes

- The chosen solution does not require any change to `PipelineState` because all needed optional timing fields already
  exist.
- The plan intentionally avoids ASR or transcription dependencies for the first implementation. Subtitle timing should
  come from voice metadata already produced by the pipeline.
- The existing placeholder code should be removed rather than gradually expanded. The prompt explicitly says not to
  optimize for backward compatibility.
- The most important architectural risk is storage staging. If `video_path` or subtitle assets are not locally
  materialized before invoking `ffmpeg`, the implementation will be fragile for non-local backends.
- The most important product risk is subtitle readability. The implementation should prefer short mobile-readable cues
  over mechanically mirroring one voice segment to one subtitle card.
- The implementation example should follow the established project pattern visible in `examples/video_assembly_demo.py`
  and `examples/voice_tool_example.py`: runnable from project root, deterministic, and usable offline.

## 5. Ask clarification on unclear topic

### Question 1

Should the first implementation allow a single `audio_segments` item to be split into multiple subtitle cues for
readability, or should every segment map to exactly one cue?

Answer: Allow segment splitting for readability, but preserve the parent segment timing envelope and
distribute durations proportionally.

### Question 2

Do you want subtitle styling to stay hardcoded as one mobile-first default in v1, or should we introduce new subtitle
style settings in `app/core/config.py` immediately?

Answer: Start with one centralized default style in code and delay public configuration until the rendering
behavior is stable.

### Question 3

Is it acceptable to extend `app/services/storage.py` with a local staging/materialization API so `ffmpeg` can consume
assets even when `STORAGE_BACKEND=s3`?

Answer: Yes. Add a small explicit staging capability to the storage abstraction instead of baking S3 path
parsing directly into `SubtitleTool`.

### Question 4

Should `examples/subtitle_tool_example.py` generate its own demo assembled video like `examples/video_assembly_demo.py`,
or should it assume an existing `video_path` artifact is already present?

Answer: Generate demo media on the fly so the example stays fully offline, deterministic, and easy to run
from a clean checkout.
