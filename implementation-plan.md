# Implementation Plan - Video Assembly

## 1. Description of the problem

Shorts Factory is a LangChain LCEL pipeline that turns a topic into a full vertical YouTube Short:

`topic -> script -> voice -> visuals -> video assembly -> subtitles -> publishing`

The current missing production-ready stage is `VideoAssemblyTool`.

From `AGENTS.md`, `README.md`, and `brainstorming.md`, the implementation must satisfy these constraints:

- consume `visual_assets` from `VisualTool`
- consume `audio_path` from `VoiceTool`
- return `video_path` in `PipelineState`
- remain a single public pipeline node named `VideoAssemblyTool`
- avoid mutating state in place
- use `ffmpeg` via `subprocess.run(..., check=True, capture_output=True)`
- use `app.services.storage.get_storage()` for persisted outputs
- remain executable without API keys
- stay deterministic and idempotent per `job_id`

The current `app/tools/video_tool.py` already contains a minimal prototype:

- it reads `visual_assets`
- concatenates clips with ffmpeg
- muxes narration audio
- saves the resulting MP4 as `{job_id}/video.mp4`

The main problem is therefore not inventing Video Assembly from scratch. The real problem is replacing the current thin
prototype with a hardened implementation that:

- validates inputs explicitly
- sorts clips deterministically
- handles temp files safely
- logs meaningful assembly events
- is easy to unit test offline
- leaves room for future timeline logic without introducing a full media-engine abstraction too early

## 2. Description of the chosen solution

The chosen solution from `brainstorming.md` is:

**Modular assembler around the ffmpeg concat demuxer**

This means:

- keep `VideoAssemblyTool` as the only public pipeline step
- keep using the concat demuxer as the rendering backend, because `VisualNormalizer` already guarantees uniform MP4
  clips
- move the logic into small internal components or helper functions so validation, planning, rendering, and probing are
  isolated and testable

Target internal design:

- `VideoAssemblyTool`
    - orchestrates the stage
    - reads `PipelineState`
    - returns `{**state, "video_path": ...}`
- `AssemblyPlan`
    - typed internal representation of ordered clips, audio input, output key, and duration metadata
- validation/build-plan helpers
    - reject empty or malformed manifests
    - ensure paths exist and are local enough for ffmpeg
    - compute deterministic ordering and expected durations
- render helpers
    - write the concat list file
    - execute ffmpeg concat
    - mux narration audio
    - persist the final output
- optional media probing helper
    - centralize audio/video duration checks

External research relevant to the chosen solution:

- Google research on official FFmpeg docs confirms the concat demuxer is appropriate when all files share the same
  stream structure and timing characteristics.
- Google research on official FFmpeg docs also surfaced the concat demuxer's `duration` directive, which can be useful
  if stored media durations are inaccurate and the implementation later needs more explicit timeline control.
- Google research on official Python docs confirms `tempfile.mktemp` is deprecated because of race-condition risks.
- Context7 resolved the authoritative Python standard library reference as `/python/cpython`, which is the relevant doc
  source for using `tempfile.NamedTemporaryFile`, `tempfile.TemporaryDirectory`, and `subprocess` safely in this stage.

Relevant notes carried forward from `brainstorming.md`:

- `VisualNormalizer` already outputs `1080x1920`, `30 fps`, `yuv420p`, audio-free MP4 clips. This is the main reason
  concat demuxer is the preferred backend.
- `SubtitleTool` only needs `video_path`, so subtitle logic must stay out of this stage.
- The current prototype uses `tempfile.mktemp`; the implementation should replace that with safer temp-file handling.
- `STORAGE_BACKEND=s3` is a design risk because ffmpeg cannot be treated as if it can always read storage URIs like
  local paths.
- For v1, the recommended policy is to keep straight cuts only and use narration audio as the timeline source of truth
  when duration drift requires a decision.

## 3. Detailed implementation plan

- [x] Remove the legacy prototype assumptions from `app/tools/video_tool.py` and lock the target architecture: one
  public `VideoAssemblyTool`, modular internal helpers, no backward-compatibility shims.
- [x] Run `pytest` and `ruff check app/ tests/` and fix any failing tests before continuing.

- [x] Introduce a typed internal assembly contract for the stage, such as `AssemblyPlan` and, if useful, a per-clip
  helper structure storing ordered path, section, chunk index, start/end timing, and duration metadata.
- [x] Add or update unit tests to cover assembly-plan construction, including deterministic ordering by `start_ms` and
  `chunk_index`.
- [x] Run `pytest` and `ruff check app/ tests/` and fix any failing tests.

- [x] Implement strict input validation for `VideoAssemblyTool`:
    - reject empty `visual_assets`
    - reject missing `audio_path`
    - reject malformed asset entries
    - reject missing or unreadable clip files
    - reject unsupported non-local asset paths for the v1 local-ffmpeg path
- [x] Add or update unit tests for each validation branch with clear error messages.
- [x] Run `pytest` and `ruff check app/ tests/` and fix any failing tests.

- [x] Replace all unsafe temporary-path handling with safe temporary resource management using `TemporaryDirectory`
  and/or `NamedTemporaryFile(delete=False)` plus explicit cleanup.
- [x] Add or update unit tests around temp-file creation behavior where testable, or mock subprocess boundaries to
  verify temporary artifacts are created through the safe path.
- [x] Run `pytest` and `ruff check app/ tests/` and fix any failing tests.

- [x] Implement the concat list writer as a dedicated helper:
    - sort assets deterministically
    - write an `ffconcat version 1.0` header
    - write escaped absolute clip paths
    - decide whether to emit `duration` directives based on trusted manifest metadata
- [x] Add or update unit tests for concat-list generation and path ordering.
- [x] Run `pytest` and `ruff check app/ tests/` and fix any failing tests.

- [x] Implement the visual assembly helper that invokes ffmpeg concat for the normalized MP4 clips and produces an
  intermediate concatenated video file.
- [x] Add or update unit tests that assert the expected ffmpeg command shape, including concat demuxer flags and failure
  propagation behavior.
- [x] Run `pytest` and `ruff check app/ tests/` and fix any failing tests.

- [x] Implement the audio mux helper that combines the concatenated visual track with `audio_path`, encodes audio to AAC
  if needed, and writes the final subtitle-ready MP4.
- [x] Add or update unit tests for the mux command construction and error handling.
- [x] Run `pytest` and `ruff check app/ tests/` and fix any failing tests.

- [x] Implement duration probing and validation policy:
    - compare total visual duration against narration duration
    - define a v1 tolerance threshold
    - log warnings when drift exceeds tolerance
    - enforce the chosen v1 policy for larger drift, most likely "audio wins"
- [x] Add or update unit tests for duration mismatch scenarios, including acceptable drift and large-drift handling.
- [x] Run `pytest` and `ruff check app/ tests/` and fix any failing tests.

- [x] Implement final persistence and logging:
    - persist the completed MP4 through `storage.save(f\"{job_id}/video.mp4\", ...)`
    - keep the return contract as `{**state, "video_path": final_path}`
    - add structured logs for validation, concat start/end, mux start/end, and output persistence
- [x] Add or update unit tests to verify deterministic output key generation and final state shape.
- [x] Run `pytest` and `ruff check app/ tests/` and fix any failing tests.

- [x] Add dedicated offline integration-style coverage in `tests/test_video_tool.py` using generated stub clips and
  silent audio so the stage can be verified without external APIs.
- [x] Run `pytest` and `ruff check app/ tests/` and fix any failing tests.

- [x] Update any pipeline-level smoke tests only if the refactor changes how existing tests instantiate or assert
  `VideoAssemblyTool`.
- [x] Run `pytest` and `ruff check app/ tests/` and fix any failing tests.

- [x] Create an example script in `examples/`, such as `examples/video_assembly_demo.py`, showing how to build a minimal
  `PipelineState` with normalized local clips plus a local audio file and invoke `VideoAssemblyTool` directly.
- [x] Add any small helper assets or generation instructions needed for the example, but keep the example fully local
  and deterministic.
- [x] Run `pytest` and `ruff check app/ tests/` and fix any failing tests.

## 4. Notes

- The implementation should stay biased toward KISS. The repo already solved clip normalization upstream, so Video
  Assembly should reuse that guarantee instead of rebuilding normalization or switching immediately to a
  filtergraph-based timeline engine.
- The first version should use straight cuts only. Transitions, overlays, background music, and ducking are future
  features and should not shape the initial architecture more than necessary.
- If the implementation grows substantially, moving internal helpers into `app/video/` is reasonable. If it stays
  compact, keeping the helpers in `app/tools/video_tool.py` is preferable.
- The v1 implementation should remove legacy temp-path behavior and unsupported assumptions rather than preserving them.
- If S3-backed storage must be supported during assembly, the likely design will be explicit local staging before ffmpeg
  runs and upload after render. That is a separate implementation concern from the concat-demuxer architecture itself.
- The main impacted tests are likely to be:
    - new tests in `tests/test_video_tool.py`
    - possible updates to pipeline smoke tests if construction details change
    - no expected changes to script, voice, or visual tests unless shared helpers move

## 5. Ask clarification on unclear topic

### Question 1

Should v1 of `VideoAssemblyTool` support `STORAGE_BACKEND=s3` during rendering, or is local filesystem support
sufficient for the first implementation?

Answer:local filesystem support is sufficient for v1. If S3 support is needed, implement explicit local
staging rather than trying to feed storage URIs directly into ffmpeg.

### Question 2

When narration audio duration and total visual duration differ materially, should the implementation:

- fail fast
- trim visuals
- extend the last visual clip

Answer:narration audio should be the source of truth for v1, and the safest adjustment is to extend or trim
only the last visual clip when drift exceeds a defined tolerance.

### Question 3

Do you want the internal refactor to stay inside `app/tools/video_tool.py`, or should the implementation introduce new
modules such as `app/video/plan.py` and `app/video/assembler.py` immediately?

Answer: immediately

### Question 4

Should the example script at the end of the implementation use checked-in tiny fixture media files, or should it
generate its own local stub media on the fly?

Answer: generate its own local stub media on the fly?
