# Implementation Plan — Visual Generation (Visual Agent)

## 1. Description of the problem

Shorts Factory needs to upgrade its visual stage from a thin stock-footage fetcher into a real **Visual Agent** that can
transform structured script data and voice timing metadata into a reusable sequence of visual assets for downstream
video assembly.

Today, `app/tools/visual_tool.py` only:

- reads `state["script"]["title"]`
- searches Pexels for portrait videos
- downloads a few results
- falls back to a solid-color clip
- returns `image_paths`

That behavior keeps the pipeline runnable, but it is not sufficient for the chosen design because it does not:

- plan visuals at the `hook` / `body` / `cta` level
- reuse `audio_segments` and `audio_duration_ms` already produced by `VoiceTool`
- distinguish images from clips in a first-class manifest
- support multiple providers behind a clean contract
- produce rich metadata for `VideoAssemblyTool` and future stages

### Workspace-specific interpretation

The request references an external planning prompt under `project-sma`, but the active workspace and confirmed analysis
are for **Shorts Factory**. This implementation plan therefore uses:

- `brainstorming.md` as the chosen-solution source of truth
- `AGENTS.md` for project rules and architecture
- the current Shorts Factory codebase for concrete file and test impacts

### Relevant repository context

- `PipelineState` currently carries `script`, `audio_path`, `audio_segments`, `audio_duration_ms`, and `image_paths`.
- `VoiceTool` already persists segment timing metadata.
- `VideoAssemblyTool` currently consumes `image_paths` only.
- `AGENTS.md` requires:
    - `PipelineTool` inheritance
    - immutable state updates
    - deterministic degraded mode
    - storage via `get_storage()`
    - structured logging

### Documentation check

The prompt asks to check `docs/features/` for relevant documentation. In this repository, there is **no `docs/features/`
directory**. The only repo documentation under `docs/` is `docs/voice_module.md`, which is helpful for consistency in
how a tool can expose richer metadata through `PipelineState`, but there is no existing visual-specific feature doc to
reuse.

---

## 2. Description of the chosen solution

The chosen solution from `brainstorming.md` is:

> **Solution 2 — Provider-based Visual Planner inside a dedicated `VisualTool`**

### Core idea

Keep a single public pipeline stage, `VisualTool`, but refactor its internals into composable pieces:

- a **planner** that converts script and timing data into a visual segment plan
- one or more **providers** that resolve each segment into a concrete asset
- a **normalizer** that ensures assets are locally available and assembly-ready
- an updated **state contract** that promotes a rich `visual_assets` manifest

This preserves the existing LCEL pipeline shape while making the visual stage extensible and testable.

### Chosen design goals

The implementation should prioritize:

- deterministic planning from `script` + `audio_segments`
- a provider abstraction that supports:
    - stock clips
    - generated still images
    - future local-library assets
    - deterministic fallback assets
- explicit, reusable visual metadata for downstream assembly
- compatibility with Shorts formatting constraints (vertical 9:16 output)

### External research applied to the plan

Brief external research supports the chosen direction:

1. **LangChain Runnable composition**
    - LangChain’s `Runnable` model and pipeline composition patterns support keeping `VisualTool` as one pipeline node
      while delegating internal orchestration to helper classes.
    - This matches the current repository style (`ScriptChain`, `VoiceTool`, `VisualTool`, etc.) and avoids introducing
      unnecessary graph complexity in V1.

2. **Stock provider support**
    - Pexels supports portrait-oriented video search and remains a suitable stock-video provider.
    - Pixabay provides both images and videos and is a practical future secondary provider.

3. **Nano Banana 2 preference**
    - Current public material indicates **Nano Banana 2** is Google’s fast AI image-generation model.
    - For this plan, it should be treated as the **default planned AI still-image provider/model** when generated
      imagery is enabled.
    - This should remain configurable through project settings and must not weaken degraded mode.

### Notes carried over from `brainstorming.md`

The following implementation assumptions are already decided and should shape the work:

- only the **Shorts Factory** interpretation is relevant going forward
- V1 should support a mix of **video clips and still images**
- timing should come primarily from `audio_segments`
- `visual_assets` should replace `image_paths` as the richer public state contract
- V1 should remain **deterministic and provider-driven**, even if an AI image provider is added

### Proposed target architecture

Recommended components for implementation:

- `VisualPlanner`
    - derive section-aware visual requests from `script` and `audio_segments`
    - fall back to deterministic equal-split timing when voice metadata is unavailable
- `VisualProvider` protocol / base abstraction
    - defines how one request becomes one resolved asset
- `PexelsVisualProvider`
    - primary stock-video provider
- `NanoBananaVisualProvider`
    - default planned AI still-image provider, using Nano Banana 2
- `FallbackVisualProvider`
    - produces safe local fallback assets when no network/API is available
- `VisualNormalizer`
    - ensures local files exist in a format the assembly stage can use consistently
- `VisualTool`
    - orchestrates planner → provider → normalizer → state enrichment
- updated `VideoAssemblyTool`
    - consumes `visual_assets` instead of only `image_paths`

---

## 3. Detailed implementation plan

### Phase A — Define the new visual contract

- [x] Define a `VisualAsset` typed structure in `app/chains/state.py` (or a closely related typed location) with fields
  such as `section`, `asset_type`, `provider`, `path`, `duration_ms`, `start_ms`, `end_ms`, `prompt`, `width`, and
  `height`.
- [x] Extend `PipelineState` to include `visual_assets` and any additional optional metadata needed for downstream
  assembly.
- [x] Remove reliance on `image_paths` as the primary contract in the plan for upcoming code changes, while deciding
  whether a temporary mirror field is needed during refactor execution.
- [x] Update any inline docs/comments that describe the visual output shape so the codebase points to `visual_assets`
  rather than a raw list of clip paths.
- [x] Add or update unit tests that validate the new typed visual state contract.
- [x] Run all tests and fix failing tests.

### Phase B — Add configuration for provider selection and Nano Banana 2 defaults

- [x] Extend `app/core/config.py` with visual-provider settings, including a configurable default provider strategy and
  a default AI image model value for **Nano Banana 2**.
- [x] Decide the minimum config surface needed for V1, such as:
    - `visual_provider`
    - `visual_ai_model`
    - credentials or endpoint settings for the AI image backend
    - stock-provider tuning fields if needed
- [x] Document in the implementation notes that Nano Banana 2 should be the default planned generated-image model, but
  fallback visuals must still work when no AI credentials are present.
- [x] Plan corresponding `.env.example` and `README.md` updates for the later implementation phase.
- [x] Add or update config-focused unit tests for new defaults and validation behavior.
- [x] Run all tests and fix failing tests.

### Phase C — Implement the deterministic visual planner

- [x] Create a `VisualPlanner` component that converts `script` and `audio_segments` into a list of section-aligned
  visual requests.
- [x] Define deterministic planning rules for:
    - `hook`
    - `body`
    - `cta`
    - multi-chunk `body` sections from `audio_segments`
- [x] Implement primary timing derivation from `audio_segments` and a fallback equal-split strategy when segment
  metadata is missing or malformed.
- [x] Define prompt/query generation rules that stay deterministic in V1 and do not depend on an LLM.
- [x] Ensure the planner emits enough metadata for downstream provider selection and normalization.
- [x] Add unit tests for planner output shape, timing alignment, fallback timing, and prompt determinism.
- [x] Run all tests and fix failing tests.

### Phase D — Introduce the provider abstraction layer

- [x] Create a `VisualProvider` abstraction (protocol, base class, or similarly lightweight contract) that can resolve
  one planned visual request into one asset result.
- [x] Design the provider API so implementations can be injected into `VisualTool` for easy unit testing.
- [x] Define a resolved-asset shape that captures provider name, file type, local path/bytes handling, duration hints,
  and optional attribution/source data.
- [x] Keep provider construction lazy so tests can instantiate `VisualTool()` without network side effects, matching the
  project’s current dependency-injection patterns.
- [x] Add unit tests around provider selection/orchestration behavior using fakes or stubs.
- [x] Run all tests and fix failing tests.

### Phase E — Build the stock-video provider

- [x] Refactor current Pexels logic out of `app/tools/visual_tool.py` into a dedicated `PexelsVisualProvider`.
- [x] Improve provider logic to select better candidate media deterministically rather than always using the first file
  variant.
- [x] Ensure the stock provider persists assets through `get_storage()` and uses deterministic storage keys based on
  `job_id` and segment index.
- [x] Normalize provider error handling so network failures cleanly fall through to the fallback path instead of
  breaking the entire pipeline when degraded mode should continue.
- [x] Add unit tests for successful stock resolution, empty-result fallback behavior, and deterministic storage keys.
- [x] Run all tests and fix failing tests.

### Phase F — Plan the Nano Banana 2 image provider

- [x] Add a dedicated AI still-image provider to the plan, named clearly enough to reflect its role (for example,
  `NanoBananaVisualProvider`).
- [x] Decide the exact integration surface for Nano Banana 2 during implementation (API client choice, request/response
  handling, auth path, and whether the repo will call a Gemini/Google endpoint directly or via a wrapper service).
- [x] Design the provider so it produces generated **still images** that can later be adapted into assembly-ready visual
  segments.
- [x] Ensure the provider remains optional and configurable; missing credentials must route the request to the
  deterministic fallback provider.
- [x] Add unit tests using injected fake clients so no live AI generation is needed during test runs.
- [x] Run all tests and fix failing tests.

### Phase G — Add fallback and normalization behavior

- [x] Replace the current single solid-color fallback helper with a reusable `FallbackVisualProvider` or equivalent
  fallback component.
- [x] Support fallback generation for both:
    - clip-like assets
    - still-image assets
- [x] Create a `VisualNormalizer` component that ensures all resolved assets are suitable for downstream ffmpeg
  assembly.
- [x] Decide how still images will be represented for assembly in V1:
    - converted into timed clip segments before assembly, or
    - passed as image assets for `VideoAssemblyTool` to animate/render
- [x] Keep ffmpeg invocation rules aligned with `AGENTS.md` requirements: `check=True`, `capture_output=True`, and no
  `shell=True`.
- [x] Add unit tests for fallback outputs, normalization decisions, and malformed-input handling.
- [x] Run all tests and fix failing tests.

### Phase H — Refactor `VisualTool` to orchestrate the new components

- [x] Rewrite `app/tools/visual_tool.py` so it becomes an orchestrator instead of a monolithic fetcher.
- [x] Inject or lazily resolve planner, providers, storage, and normalizer dependencies.
- [x] Preserve immutable state updates and structured logging.
- [x] Make the tool idempotent by using deterministic storage keys tied to `job_id` and segment order.
- [x] Return `visual_assets` as the primary output contract.
- [x] Remove legacy code paths that no longer match the chosen architecture.
- [x] Add focused `tests/test_visual.py` coverage for:
    - happy path with multiple providers
    - degraded-mode fallback path
    - no mutation of input state
    - deterministic persistence behavior
- [x] Run all tests and fix failing tests.

### Phase I — Update `VideoAssemblyTool` for `visual_assets`

- [x] Refactor `app/tools/video_tool.py` to consume `visual_assets` instead of assuming `image_paths` is a list of
  ready-made clips.
- [x] Decide the assembly strategy for mixed media:
    - concatenate video clips directly
    - render still images into timed segments
    - normalize the final sequence to a consistent vertical output pipeline
- [x] Ensure the assembly stage respects segment durations from `visual_assets`.
- [x] Preserve compatibility with audio muxing and the current storage flow.
- [x] Add targeted unit tests for mixed-media assembly planning and failure handling.
- [x] Update `tests/test_pipeline.py` so the smoke pipeline uses `visual_assets` instead of `image_paths`.
- [x] Run all tests and fix failing tests.

### Phase J — Documentation and final cleanup

- [x] Update `AGENTS.md` if the Visual Agent contract or documented output fields change materially.
- [x] Update `README.md` to describe the new visual architecture, supported asset types, and new configuration
  variables.
- [x] Update `.env.example` with visual-provider and Nano Banana 2-related settings during implementation.
- [x] Review naming to eliminate misleading terminology such as `image_paths` where it no longer reflects the real
  contract.
- [x] Run the full test suite and fix remaining failures.
- [x] Run lint/quality checks and fix remaining issues.

---

## 4. Notes

### Implementation sequencing guidance

- Start by defining the **state contract** before touching provider logic. This reduces churn later.
- Keep `VisualTool` thin and orchestration-focused, similar in spirit to how `VoiceTool` delegates work to other
  components.
- Prefer small, testable helper modules rather than one large visual file.
- Introduce the planner before the AI provider so deterministic behavior is established first.

### Testing strategy notes

- There is currently **no dedicated visual test module**, so `tests/test_visual.py` should be added in the
  implementation phase.
- `tests/test_pipeline.py` will definitely be impacted because the visual step contract is changing.
- Config tests may need expansion if new visual settings are added.
- Provider tests should use injected fake clients rather than live network calls.
- ffmpeg-heavy paths should be isolated so unit tests can remain fast and deterministic.

### Nano Banana 2 planning note

The user’s preference is to use **Nano Banana 2 by default**. For planning purposes, that should mean:

- it is the default **generated-image** model in configuration
- it is not required for degraded mode
- it should be wrapped behind a provider abstraction rather than called directly from `VisualTool`
- tests must not depend on live access to the model

### Out-of-scope for this phase

- implementing the visual architecture
- wiring live credentials for Nano Banana 2
- adding human review, scoring, or LangGraph branching

---

## 5. Ask clarification on unclear topic

### Question 1

What exact integration path should be used for **Nano Banana 2** during implementation?

- direct Google / Gemini API calls
- Google AI Studio-compatible endpoint
- Vertex AI
- an internal wrapper service

Answer: **Direct Gemini API calls via the `google-genai` Python SDK.**

Nano Banana 2 is the codename for **Gemini 3.1 Flash Image** (`gemini-3.1-flash-image`). Google's own documentation
[explicitly recommends](https://github.com/googleapis/python-genai/blob/main/codegen_instructions.md) the unified
`google-genai` package (not the legacy `google-generativeai`) for all Gemini API requests. The same SDK targets both
the Gemini Developer API (AI Studio key) and Vertex AI via a single `genai.Client` constructor parameter, so no
integration path lock-in occurs.

**Recommended V1 approach:**

```python
# app/services/nano_banana.py
from google import genai
from google.genai import types

def generate_image(prompt: str, api_key: str) -> bytes:
    client = genai.Client(api_key=api_key)
    response = client.models.generate_images(
        model="gemini-3.1-flash-image",
        prompt=prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="9:16",         # portrait / Shorts format
            output_mime_type="image/png",
        ),
    )
    return response.generated_images[0].image.image_bytes
```

- **Auth:** single `GOOGLE_API_KEY` env var (AI Studio key, free tier available) — no GCP project needed for V1.
- **Fallback:** if `GOOGLE_API_KEY` is absent or the call fails, route to `FallbackVisualProvider` — no pipeline break.
- **Vertex AI upgrade path:** swap `genai.Client(api_key=...)` for
  `genai.Client(vertexai=True, project=..., location=...)` without changing any other code.
- **Do not** use Vertex AI for V1 — it adds GCP project setup complexity with no benefit at this scale.
- **Add** `google-genai>=1.0` to `pyproject.toml` as an optional extra (e.g. `[visual]`) so the core pipeline still
  runs without it.



### Question 2

For V1 mixed-media assembly, how should **still images** behave in the final video?

- rendered into timed video segments with a static frame
- rendered with a simple pan/zoom effect
- treated as interchangeable with clips after normalization

Answer: **Rendered into timed video segments with a static frame (by the `VisualNormalizer` before assembly).**

`VideoAssemblyTool` should receive only uniform `.mp4` clips — it must never need to branch on asset type. The
`VisualNormalizer` is responsible for converting still images to fixed-duration video segments via ffmpeg before the
state is updated.

Concrete ffmpeg command (inside `VisualNormalizer`):

```bash
ffmpeg -y -loop 1 -i {image_path} -t {duration_s:.3f} \
       -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1" \
       -r 30 -pix_fmt yuv420p -an {out_path}
```

- **Duration** is taken from `VisualAsset.duration_ms`, which the planner derives from `audio_segments`.
- **Pan/zoom** (Ken Burns effect) is intentionally deferred to a later phase — it adds ffmpeg filter complexity without
  changing the V1 contract and can be introduced as an option on `VisualAsset` once the pipeline is stable.
- This keeps `VideoAssemblyTool` simple (concat + audio mux only) and makes every asset interchangeable after
  normalization.


### Question 3

Should provider selection prefer:

- stock video first, then Nano Banana 2 image generation when stock is weak or unavailable
- Nano Banana 2 first for stills and stock only for motion-heavy segments
- an explicit section-based rule (for example, stock for body, generated still for CTA)

Answer: **Explicit section-based rule — default mapping per script section, with provider fallback chain.**

| Section | Primary provider | Rationale |
|---|---|---|
| `hook` | `NanoBananaVisualProvider` | Precise, branded image with maximum visual impact to grab attention in the first 3 s |
| `body` | `PexelsVisualProvider` | Motion video holds attention through the informational segment |
| `cta` | `NanoBananaVisualProvider` | Clean, branded still frames reinforce the call-to-action message |

Each section resolves its primary provider first; if that provider fails or has no credentials, it falls through to
`FallbackVisualProvider`. This is deterministic, section-aware, and fully testable without live API calls.

The rule is encoded as a constant map in `VisualPlanner` (not hard-wired in `VisualTool`) so it can be overridden
through config or replaced section-by-section in later phases. Adding a `visual_provider_map` config entry in
`app/core/config.py` will let the default be changed per deployment without code changes.


### Question 4

Do you want the implementation phase to fully remove `image_paths` immediately, or keep a short transitional mirror
field internally until all downstream code has been updated?

Answer: **Keep a short transitional mirror field during the refactor, then remove it in Phase I.**

`VideoAssemblyTool` currently reads `state["image_paths"]` directly. Removing the field before that tool is updated
would break `tests/test_pipeline.py` and the smoke test. A clean cutover across multiple files in a single commit risks
regressions and makes git-bisect harder.

**Recommended transitional strategy:**

- **Phase H** (`VisualTool` refactor): write both `visual_assets` (new contract) **and** `image_paths` (deprecated
  mirror, populated from `[a.path for a in visual_assets]`). Mark `image_paths` as `@deprecated` in a docstring.
- **Phase I** (`VideoAssemblyTool` update): switch consumption to `visual_assets`, delete the mirror write from
  `VisualTool`, and remove `image_paths` from `PipelineState`.
- Update `tests/test_pipeline.py` in Phase I once both sides are migrated.

This keeps the full pipeline green throughout the refactor and makes each phase independently reviewable.


