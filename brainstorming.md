# Brainstorming - Video Assembly

## 1. Description of the problem

Shorts Factory already implements:

- Script Generation
- Voice Generation
- Visual Generation

The next stage to implement is `VideoAssemblyTool`.

In this repository, the Video Assembly stage must:

- read `visual_assets` from `VisualTool`
- read `audio_path` from `VoiceTool`
- output a single `video_path` for `SubtitleTool`
- remain compatible with the `PipelineState` contract in `app/chains/state.py`
- work offline in degraded mode
- use `ffmpeg` through `subprocess.run(..., check=True, capture_output=True)`
- persist the result through `app.services.storage.get_storage()`
- remain deterministic and idempotent per `job_id`

Important repo-specific observations:

- `app/visual/normalizer.py` already outputs assembly-ready clips:
    - `1080x1920`
    - `30 fps`
    - `yuv420p`
    - `.mp4`
    - no audio track (`-an`)
- `app/visual/models.py` already gives the assembly stage timing metadata per asset:
    - `start_ms`
    - `end_ms`
    - `duration_ms`
- `app/tools/subtitle_tool.py` only needs `video_path`, so subtitle rendering should stay out of Video Assembly.
- `app/tools/video_tool.py` already contains a basic concat-plus-mux implementation, so the problem is not "invent video
  assembly from zero", but "choose the right architecture for a production-ready version of the stage".

The core design question is:

How should we assemble already-normalized vertical clips plus narration audio into one deterministic MP4 while keeping
the implementation simple enough for the current repo, but extensible enough for future timeline features?

## 2. Research summary

Online research was limited to official FFmpeg documentation.

Sources:

- [FFmpeg Formats Documentation - concat demuxer](https://ffmpeg.org/ffmpeg-formats.html)
- [FFmpeg Filters Documentation - concat filter](https://ffmpeg.org/ffmpeg-filters.html)
- [FFmpeg Documentation - -shortest](https://ffmpeg.org/ffmpeg.html)

Key findings:

- The concat demuxer is a strong fit when files already share the same stream layout, codec family, and time base. The
  FFmpeg docs explicitly state that it reads a text list of files and that all files must have the same streams, codecs,
  and timing characteristics.
- The concat filter is more flexible than the concat demuxer, but it requires more explicit filtergraph management. The
  FFmpeg docs note that segments must start at timestamp `0`, and corresponding streams must have matching parameters
  unless explicitly converted.
- The `-shortest` output option ends encoding when the shortest stream ends. This is useful when muxing narration audio
  with concatenated visuals, but it is not a complete duration-reconciliation policy by itself.
- FFmpeg supports more advanced filtergraph-based composition, which is useful when timeline rules become more complex,
  but this also increases implementation and debugging complexity.

What the research means for this repo:

- Because `VisualNormalizer` already guarantees normalized MP4 clips, Shorts Factory is unusually well-positioned to use
  the concat demuxer safely.
- The repo does not yet need a cinematic timeline engine. It needs a reliable assembly step that works with the current
  visual contract.
- The best first implementation should take advantage of the strong upstream normalization guarantees instead of
  rebuilding timeline logic too early.

## 3. Thinking process

### 3.1 Gather and analyze project information

The assembly stage is not operating on arbitrary media. It receives a constrained, well-shaped manifest:

- `visual_assets` is already normalized into uniform MP4 clips.
- `audio_path` already points to the merged narration audio.
- `audio_duration_ms` may be available and can help with validation.
- The stage writes exactly one new output into state: `video_path`.

This matters because it narrows the problem significantly.

We do not need:

- image-to-video rendering in this stage
- provider selection
- prompt generation
- subtitle burn-in
- YouTube metadata handling

We do need:

- deterministic clip ordering
- asset existence validation
- duration sanity checks
- a local ffmpeg working strategy
- storage persistence for the final MP4

Potential repo risks discovered during analysis:

- `Storage.save()` returns a string path, but if `STORAGE_BACKEND=s3`, downstream ffmpeg commands cannot safely assume
  the path is a local filesystem path.
- The current `app/tools/video_tool.py` uses `tempfile.mktemp`, which should be avoided in the hardened implementation.
- The current tool assumes clip durations are already correct enough to concatenate and then truncates with `-shortest`;
  that is acceptable for an MVP but not a full design decision.

### 3.2 Algorithm

The practical algorithm for this repo should be:

1. Read `visual_assets` and `audio_path` from state.
2. Validate that the manifest is non-empty and sorted deterministically.
3. Validate that every referenced clip exists and is locally accessible to ffmpeg.
4. Probe or trust the normalized clip durations, then compare the total visual duration against the narration duration.
5. Build an assembly plan.
6. Render the concatenated visual stream.
7. Mux narration audio onto the rendered visual track.
8. Persist the final MP4 under a deterministic storage key such as `{job_id}/video.mp4`.
9. Validate the resulting file and return `{**state, "video_path": ...}`.

The real design choice is how sophisticated step 5 and step 6 should be.

### 3.3 Architecture direction

The public pipeline node should remain `VideoAssemblyTool`, because that matches `AGENTS.md` and the current LCEL
pipeline.

If the stage grows, the internal complexity should move into private helpers or `app/video/` modules, similar to the way
the visual stage uses `planner`, `providers`, and `normalizer`.

That leads to three realistic options.

## 4. Solutions

### Solution 1 - Thin monolithic concat demuxer tool

#### Description

Keep all logic inside `app/tools/video_tool.py`.

Implementation shape:

- sort assets by `start_ms`, then `chunk_index`
- write an ffconcat list file
- run `ffmpeg -f concat -safe 0 -i list.txt -c copy` for the visual stream
- run a second ffmpeg command to mux the narration audio
- save the result through `storage.save()`

This is the smallest possible implementation that still matches the current repo contract.

It works well because upstream normalization already guarantees:

- same resolution
- same fps
- same pixel format
- same container family
- no per-clip audio streams

#### Example

```python
assets = sorted(
    state["visual_assets"],
    key=lambda asset: (asset["start_ms"], asset["chunk_index"]),
)

with NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
    handle.write("ffconcat version 1.0\n")
    for asset in assets:
        handle.write(f"file '{asset['path']}'\n")
    list_path = handle.name

subprocess.run(
    [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        concat_path,
    ],
    check=True,
    capture_output=True,
)

subprocess.run(
    [
        "ffmpeg", "-y",
        "-i", concat_path,
        "-i", state["audio_path"],
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        out_path,
    ],
    check=True,
    capture_output=True,
)
```

### Solution 2 - Modular assembler around concat demuxer

#### Description

Keep `VideoAssemblyTool` as the public pipeline step, but move the work into small internal building blocks.

Suggested internal responsibilities:

- `AssemblyValidator`: validates state, paths, ordering, and minimum invariants
- `AssemblyPlan`: stores ordered clips, total visual duration, audio duration, and final output key
- `FFmpegConcatAssembler`: writes the ffconcat list, renders the visual stream, muxes audio, validates the final file
- optional `MediaProbe`: centralizes duration probing for audio/video

The rendering backend still uses the concat demuxer, because that is the simplest and most appropriate backend for the
already-normalized inputs. The difference from Solution 1 is architectural: the stage becomes testable, explainable, and
ready for future policy decisions.

This approach also gives us one place to define duration policy, for example:

- if drift is tiny, allow `-shortest`
- if visual total is meaningfully shorter than audio, extend only the last clip
- if an asset path is non-local, fail fast with a clear message or stage it locally first

#### Example

```python
class VideoAssemblyTool(PipelineTool):
    name = "VideoAssemblyTool"

    def run(self, state: PipelineState) -> PipelineState:
        storage = get_storage()
        validator = AssemblyValidator()
        probe = MediaProbe()
        assembler = FFmpegConcatAssembler(storage=storage, probe=probe)

        plan = validator.build_plan(state, probe=probe)
        video_path = assembler.render(plan)
        return {**state, "video_path": video_path}
```

Possible plan model:

```python
@dataclass(frozen=True, slots=True)
class AssemblyPlan:
    job_id: str
    audio_path: str
    clips: list[str]
    audio_duration_ms: int | None
    visual_duration_ms: int
    output_key: str
```

### Solution 3 - Filtergraph timeline renderer

#### Description

Build a real timeline renderer around `ffmpeg -filter_complex` instead of using the concat demuxer as the primary render
path.

This approach would:

- open each clip as its own ffmpeg input
- optionally trim or pad each clip
- concatenate within a filtergraph
- optionally support transitions like `xfade`
- mux audio in the same render pipeline or in a final pass

This is the most flexible design. It becomes attractive if the roadmap soon includes:

- animated transitions
- overlays
- text layers
- background music
- ducking
- per-section effects

For the current repo, however, it is the highest-complexity option and asks the implementation to solve problems that
the upstream visual normalization stage has already solved for us.

#### Example

```bash
ffmpeg -y \
  -i clip1.mp4 -i clip2.mp4 -i clip3.mp4 -i voice.mp3 \
  -filter_complex "\
    [0:v][1:v][2:v]concat=n=3:v=1:a=0[v]" \
  -map "[v]" -map 3:a \
  -c:v libx264 -c:a aac -shortest output.mp4
```

Or, with future transitions:

```bash
ffmpeg -y \
  -i clip1.mp4 -i clip2.mp4 -i voice.mp3 \
  -filter_complex "\
    [0:v][1:v]xfade=transition=fade:duration=0.25:offset=2.75[v]" \
  -map "[v]" -map 2:a \
  -c:v libx264 -c:a aac output.mp4
```

## 5. Comparison criteria & Summary Table

### Comparison criteria

- Fit with the current repo contracts
- Implementation complexity
- Deterministic behavior
- Offline compatibility
- Robustness to duration mismatches
- Testability
- Future extensibility
- Operational ffmpeg complexity

### Summary Table

| Solution                                   | Fit with current repo | Complexity | Determinism | Extensibility | Main strength                                          | Main weakness                                  |
|--------------------------------------------|-----------------------|------------|-------------|---------------|--------------------------------------------------------|------------------------------------------------|
| 1. Thin monolithic concat demuxer tool     | High                  | Low        | High        | Low           | Fastest path to a working stage                        | Logic becomes harder to test and extend        |
| 2. Modular assembler around concat demuxer | Very high             | Medium     | High        | Medium-high   | Best balance of KISS, testability, and growth          | Slightly more design work up front             |
| 3. Filtergraph timeline renderer           | Medium                | High       | Medium-high | Very high     | Best long-term flexibility for effects and transitions | Over-engineered for the current input contract |

### Ranked solutions

1. Solution 2 - Modular assembler around concat demuxer
2. Solution 1 - Thin monolithic concat demuxer tool
3. Solution 3 - Filtergraph timeline renderer

## 6. Chosen solution

### Recommended choice

Choose **Solution 2 - Modular assembler around concat demuxer**.

### Why this is the best fit

- It respects the repo's current architecture: keep `VideoAssemblyTool` as the single public pipeline node.
- It uses the strongest fact in the codebase: `VisualNormalizer` already produces concat-friendly clips.
- It stays close to the current implementation, so implementation risk stays low.
- It creates explicit seams for unit tests, which the current video stage is missing.
- It gives a clean place to handle duration policy, path validation, and future staging of remote assets if needed.
- It does not force the project into a full timeline engine before there is a real product need for one.

### Recommended implementation shape

Public entry point:

- `app/tools/video_tool.py`

Suggested internal structure:

- keep `VideoAssemblyTool.run()` thin
- add small private helpers in the same file first, or introduce `app/video/` only if the code becomes large enough to
  justify it
- centralize validation and probing before the first ffmpeg command

Recommended responsibilities:

- `VideoAssemblyTool`
    - orchestrates dependencies
    - reads state
    - returns `{**state, "video_path": ...}`
- `build_assembly_plan(...)`
    - sorts clips
    - validates manifest fields
    - determines output key
    - computes expected total duration
- `render_concat_video(...)`
    - writes ffconcat list
    - renders concatenated visual track
    - muxes narration audio
- `probe_duration(...)`
    - optional wrapper around `ffprobe` or validated ffmpeg metadata extraction

### Recommended duration policy

For v1:

- treat the normalized clip manifest as the primary visual timeline
- mux narration audio with `-shortest`
- add explicit validation and logging when total visual duration and audio duration differ beyond a small tolerance
- if large drift appears in practice, extend or trim only the last clip rather than redesigning the entire renderer

### Recommended test plan

Add dedicated `tests/test_video_tool.py` coverage for:

- empty `visual_assets` -> raises clear error
- asset sorting is deterministic
- local offline assembly succeeds with generated stub clips and silent audio
- output file is written to deterministic storage location
- major duration mismatch is surfaced clearly

## 7. Notes

- The current `app/tools/video_tool.py` is already a usable prototype. The analysis above recommends hardening and
  structuring it, not discarding it.
- `VisualTool` already guarantees the most important ffmpeg preconditions, which strongly favors a concat-demuxer-based
  implementation.
- `SubtitleTool` consumes `video_path` only, so Video Assembly should stay focused on clip sequencing and audio muxing.
- `Storage` currently exposes `save()` and `path()` only. If `STORAGE_BACKEND=s3` must be supported during assembly, the
  repo will likely need a temporary local staging mechanism because ffmpeg cannot safely work on abstract storage URIs
  as if they were local files.
- Avoid `tempfile.mktemp` in the implementation. Prefer `TemporaryDirectory` or `NamedTemporaryFile(delete=False)` with
  explicit cleanup.
- The prompt file still contains a few older references to earlier stages. This analysis follows the actual repo
  contract instead of those stale labels.

## 8. Ask clarification on unclear topic

### Question 1

Should the first implementation of Video Assembly support `STORAGE_BACKEND=s3`, or is local filesystem storage enough
for the first version?

Answer: local filesystem support is enough for v1. If S3 support is required, add explicit download-to-temp
and upload-from-temp behavior instead of assuming ffmpeg can work directly with storage URIs.

### Question 2

If total visual duration and narration duration do not match, which should be treated as the source of truth?

Answer: narration audio should win. Trim or extend only the last visual clip within a small tolerance window
instead of changing the whole timeline strategy.

### Question 3

Do you want transitions in v1, or should the first implementation use straight cuts only?

Answer: transitions

### Question 4

Should Video Assembly remain a single-file implementation for now, or do you want new internal modules such as
`app/video/assembler.py` and `app/video/probe.py` immediately?

Answer:immediately
