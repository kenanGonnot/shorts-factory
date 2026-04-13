# Publishing Module

The publishing module owns the last step of the pipeline: turning a
persisted final MP4 plus script metadata into a YouTube upload request
or a deterministic dry-run result.

It sits after subtitle burn-in:

```
ScriptChain → VoiceTool → VisualTool → VideoAssemblyTool → SubtitleTool → PublishingTool
```

`PublishingTool` remains the only pipeline-facing class. Validation,
metadata shaping, upload eligibility checks, and YouTube API mechanics
live in dedicated internal modules.

## Architecture

```mermaid
flowchart LR
    State[PipelineState\n+ job_id\n+ script\n+ final_path] --> PT[PublishingTool]
    PT --> V[validate_state]
    V --> C[PublishContext]
    PT --> M[build_publish_metadata]
    M --> MD[PublishMetadata]
    PT --> S[publish_video]
    S --> E{resolve_upload_eligibility}
    E -->|disabled| DRY[PublishResult\nmode=dry_run\nyoutube_id=dryrun-job_id]
    E -->|enabled| STAGE[Storage.stage_local(final_path)]
    STAGE --> REQ[PublishRequest\nlocal video path + metadata]
    REQ --> YT[upload_video]
    YT --> API[YouTube videos.insert\nresumable upload]
    API --> UP[PublishResult\nmode=uploaded\nyoutube_id=<video id>]
    DRY --> OUT[PipelineState\n+ youtube_id]
    UP --> OUT
```

## Components

| Module | Responsibility |
| --- | --- |
| `app/tools/publish_tool.py` | Thin pipeline node: validates input state, builds metadata, invokes publish orchestration, logs lifecycle events, and returns `{**state, "youtube_id": ...}`. |
| `app/publishing/models.py` | Immutable dataclasses for `PublishContext`, `PublishMetadata`, `PublishRequest`, and `PublishResult`. |
| `app/publishing/validate.py` | Validates `job_id`, `final_path`, and `script` shape before any upload logic runs. |
| `app/publishing/metadata.py` | Builds YouTube-safe title, description, tags, and privacy values from the script. |
| `app/publishing/service.py` | Decides dry-run vs real upload, stages persisted assets locally, and delegates to the YouTube wrapper. |
| `app/services/youtube.py` | Focused YouTube API wrapper for credential readiness checks and resumable `videos.insert` uploads. |

## Input Contract

`PublishingTool` expects these `PipelineState` fields:

| Field | Required | Description |
| --- | --- | --- |
| `job_id` | ✅ | Stable run identifier. Used for deterministic dry-run IDs. |
| `final_path` | ✅ | Persisted final MP4 path. Can be a local path or an `s3://...` URI. |
| `script.title` | ✅ | Base video title before Shorts formatting. |
| `script.hook` | ✅ | Description section 1. |
| `script.body` | ✅ | Description section 2. |
| `script.cta` | ✅ | Description section 3. |
| `script.tags` | optional | Tag candidates for YouTube metadata. |

Validation fails early when any required field is missing or malformed.

## Output Contract

The public pipeline contract stays intentionally small:

| Field | Added by `PublishingTool` | Description |
| --- | --- | --- |
| `youtube_id` | ✅ | Real YouTube video ID after upload, or deterministic `dryrun-<job_id>` when upload is skipped. |

The richer `PublishResult` stays internal for now. Worker/API persistence
continues to store `youtube_id` only.

## Dry-Run Behavior

The publish flow stays runnable without credentials:

- If `YOUTUBE_CLIENT_SECRETS_FILE` is empty or missing, publishing falls
  back to dry-run.
- If `YOUTUBE_TOKEN_FILE` is empty or missing, publishing falls back to
  dry-run.
- Dry-run does not stage the video asset or call Google APIs.
- The returned identifier is always `dryrun-<job_id>`.

This keeps Celery workers and API handlers headless. OAuth token
bootstrap is intentionally out of scope for the runtime path.

## Metadata Rules

`build_publish_metadata()` applies deterministic normalization:

- Title always ends with exactly one `#shorts`.
- Title is truncated to YouTube's 100-character limit.
- Description is assembled from `hook`, `body`, and `cta`, then capped to
  5000 UTF-8 bytes.
- Description includes `#shorts` unless the script already contains it.
- Tags are whitespace-normalized, deduplicated case-insensitively,
  stripped of leading `#`, and kept within the 500-character YouTube tag
  budget.
- Privacy must be one of `public`, `private`, or `unlisted`.

## Real Upload Flow

When upload is enabled:

1. `PublishingTool` validates the state into a `PublishContext`.
2. Metadata is normalized into `PublishMetadata`.
3. `publish_video()` checks credential readiness.
4. `Storage.stage_local(...)` materializes the persisted final asset as a
   readable local file path.
5. `upload_video()` builds a `videos.insert` request with `snippet` and
   `status`.
6. Upload runs through a resumable `next_chunk()` loop with retry handling
   for transient 5xx failures.
7. The resulting YouTube video ID is written back to `PipelineState`.

## Usage

### As part of the LCEL pipeline

```python
from app.chains.pipeline import build_pipeline

pipeline = build_pipeline()
result = pipeline.invoke({"job_id": "job-42", "topic": "typed python"})
print(result["youtube_id"])
```

### Stand-alone in dry-run mode

```python
from app.core.config import Settings
from app.tools.publish_tool import PublishingTool

tool = PublishingTool(
    settings=Settings(
        youtube_client_secrets_file="",
        youtube_token_file="",
        youtube_privacy="private",
    )
)
result = tool.run(state_with_final_path_and_script)
print(result["youtube_id"])  # dryrun-<job_id>
```

A runnable example lives at
[`examples/publishing_tool_example.py`](../examples/publishing_tool_example.py).

## Testing

Publishing coverage is split by concern:

- `tests/test_publishing_models.py`
- `tests/test_publishing_validate.py`
- `tests/test_publishing_metadata.py`
- `tests/test_publishing_service.py`
- `tests/test_youtube_service.py`
- `tests/test_publish_tool.py`

Run the focused suite with:

```bash
uv run pytest tests/test_publish_tool.py tests/test_publishing_* tests/test_youtube_service.py -q
```

## Design Notes

- `PublishingTool` does not mutate input state.
- Storage resolution is lazy and skipped entirely on dry-run.
- The YouTube wrapper no longer exposes the legacy
  `upload_short(video_path, title, description, tags)` helper.
- The worker/API contract remains unchanged while the richer internal
  models make the stage easier to test and extend later.
