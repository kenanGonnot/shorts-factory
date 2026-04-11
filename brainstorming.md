# Brainstorming — Visual Generation (Visual Agent)

## 1. Description of the problem

We need to design the **third step** of the Shorts Factory pipeline: a **Visual Generation** module that converts a
structured script and optional voice metadata into a sequence of visual assets that can be assembled into a coherent
YouTube Short.

In the current repository, the pipeline is:

`topic → ScriptChain → VoiceTool → VisualTool → VideoAssemblyTool → SubtitleTool → PublishingTool`

The current `VisualTool` is intentionally simple:

- it reads `state["script"]["title"]`
- queries Pexels for portrait stock videos
- downloads a few clips locally
- falls back to a solid-color clip when no API key or results are available
- returns `image_paths`, even though the values are actually video clip paths

That keeps the pipeline runnable end-to-end, but it is too limited for a robust visual stage because it:

- ignores `hook`, `body`, `cta`
- ignores `audio_segments` and `audio_duration_ms` already produced by `VoiceTool`
- has no explicit asset planning step
- has no provider abstraction for stock / AI / local libraries
- has no reusable visual manifest for downstream tools

### Scope used for this analysis

There is an ambiguity in the request:

- the active workspace is **`shorts-factory`**
- the user explicitly referenced an external prompt file under **`project-sma`**, which targets a different MAS/NiceGUI
  codebase
- this repository already contains a local prompt at `/.github/prompts/dev-phase-0-analysis.prompt.md` that exactly
  matches the Shorts Factory Visual Agent problem

For this document, I used the **deliverable format** requested by the external prompt, but grounded the analysis in the
**actual Shorts Factory repository** (`AGENTS.md`, `README.md`, and the current `app/*` pipeline contracts). This is the
safest interpretation for the current workspace.

---

## 2. Research summary

### Repository findings

From `AGENTS.md`, `README.md`, and the current code:

- Every stage is a `Runnable[PipelineState, PipelineState]` and must preserve the immutable state pattern:
  `return {**state, ...}`.
- `VoiceTool` already produces useful alignment metadata:
    - `audio_segments_path`
    - `audio_segments`
    - `audio_duration_ms`
- `VideoAssemblyTool` currently expects a local list of clip paths in `image_paths` and concatenates them with ffmpeg
  before muxing audio.
- `VisualTool` currently behaves like a thin stock-fetcher, not a real planning/generation agent.
- The project requires **degraded mode**: the pipeline must still work without external API keys.
- Files should be persisted through `app.services.storage.get_storage()` and tools should stay idempotent by `job_id`
  where possible.

### External research findings

Brief web research supports the current design direction:

1. **Pexels API**
    - Search results for the official Pexels API documentation indicate that video search supports filters such as *
      *orientation**, which matches the repository’s current `orientation=portrait` usage.
    - This confirms Pexels is a reasonable stock-video source for vertical Shorts workflows.

2. **Pixabay API**
    - Pixabay’s API documentation describes a REST/JSON API for **free images and videos**.
    - This makes Pixabay a practical secondary provider or fallback provider for a future provider-based architecture.

3. **FFmpeg**
    - FFmpeg documentation confirms the core primitives already used in the repo are the right ones for assembly:
        - concat workflows
        - scaling
        - cropping
        - fixed pixel format for broad compatibility
    - This supports a design where the Visual Agent normalizes assets before assembly, rather than pushing normalization
      complexity downstream.

### Implications for Shorts Factory

The strongest conclusion is that the next iteration of the visual stage should **not** be “just another stock API
wrapper”. It should be a **two-part module**:

1. a **planner** that derives shot/asset requests from the script and timing metadata
2. one or more **providers** that resolve each request into a local asset

That keeps the pipeline modular, testable, and compatible with the project’s LangChain + `PipelineTool` architecture.

---

## 3. Thinking process

### What the Visual Agent must consume

At minimum:

- `script.title`
- `script.hook`
- `script.body`
- `script.cta`

Optionally, and ideally for V1:

- `audio_segments`
- `audio_duration_ms`

The repository already gives us segment-aware voice metadata, so the cleanest design is to reuse it instead of inventing
a new timing system.

### What the Visual Agent must produce

The output needs to be directly usable by the assembly stage. Conceptually, downstream assembly needs a list of segments
like:

- local file path
- asset type (`image` / `video`)
- intended duration
- section mapping (`hook` / `body` / `cta`)
- optional timing (`start_ms`, `end_ms`)
- optional source metadata (provider, prompt, attribution)

The current `image_paths: list[str]` is enough for a smoke test, but not enough for a scalable visual system.

### Key design constraints from this repository

Any good solution must:

- stay inside the `PipelineTool` contract
- avoid in-place mutation of `PipelineState`
- keep deterministic fallback behavior when no API keys exist
- use storage abstraction instead of ad-hoc disk I/O
- remain easy to test without network access
- integrate naturally with `VideoAssemblyTool`
- avoid unnecessary complexity for the current phase

### Design direction

I considered three realistic approaches:

1. extend the current `VisualTool` a little, but keep it mostly stock-only
2. introduce a provider-based visual planner + resolver architecture inside a single dedicated tool
3. jump directly to a graph-like, multi-stage visual orchestration system

The second option best matches the project’s current maturity level.

---

## 4. Solutions

### Solution 1 — Minimal evolution of the current `VisualTool`

#### Description

Keep one tool class and evolve it incrementally:

- split the script into a few sections (`hook`, `body`, `cta`)
- generate one search query per section with deterministic rules
- fetch stock footage for each section from Pexels
- if no match exists, generate fallback solid-color clips
- return a flat list of local asset paths for assembly

This is the smallest change from the current implementation.

#### Example

```python
state = {
    "job_id": "job-42",
    "script": {
        "title": "Why octopuses are so smart",
        "hook": "Octopuses solve problems faster than you think.",
        "body": "They have distributed neurons. Their arms can act semi-independently. That helps them explore and adapt. It is one reason they seem uncannily clever.",
        "cta": "Follow for more fast science facts.",
        "tags": ["octopus", "science", "animals", "brain", "shorts"],
    },
    "audio_duration_ms": 24000,
}

# Deterministic search queries
queries = [
    "octopus underwater close up",
    "octopus movement ocean intelligence",
    "ocean animal cinematic vertical",
]

# Output shape stays simple
out = {
    **state,
    "image_paths": [
        "/storage/job-42/clip_0.mp4",
        "/storage/job-42/clip_1.mp4",
        "/storage/job-42/clip_2.mp4",
    ],
}
```

#### When it is attractive

- fastest to ship
- lowest code churn
- works well if stock footage remains the only supported source

#### Limits

- weak abstraction boundary
- difficult to add AI generation later
- timing logic remains shallow
- downstream metadata remains poor

---

### Solution 2 — Provider-based Visual Planner inside a dedicated `VisualTool` (recommended)

#### Description

Create a dedicated visual architecture with **composition**, not a monolith:

- `VisualPlanner`: transforms `script` + optional `audio_segments` into a list of visual segment requests
- `VisualProvider`: resolves each request using one backend
    - stock provider (`Pexels`, later `Pixabay`)
    - AI provider (future)
    - local-library provider
    - deterministic fallback provider
- `VisualNormalizer`: validates / converts assets to vertical, local, assembly-ready files
- `VisualTool`: orchestrates the planner and providers, persists artifacts, and returns enriched state

This still respects the repository contract because the public pipeline node remains a single `PipelineTool`.

#### Example

```python
state = {
    "job_id": "job-42",
    "script": {
        "title": "Why octopuses are so smart",
        "hook": "Octopuses solve problems faster than you think.",
        "body": "They have distributed neurons. Their arms can act semi-independently. That helps them explore and adapt. It is one reason they seem uncannily clever.",
        "cta": "Follow for more fast science facts.",
        "tags": ["octopus", "science", "animals", "brain", "shorts"],
    },
    "audio_segments": [
        {"section": "hook", "chunk_index": 0, "text": "Octopuses solve problems faster than you think.",
         "duration_ms": 3500},
        {"section": "body", "chunk_index": 0, "text": "They have distributed neurons.", "duration_ms": 4000},
        {"section": "body", "chunk_index": 1, "text": "Their arms can act semi-independently.", "duration_ms": 4200},
        {"section": "cta", "chunk_index": 0, "text": "Follow for more fast science facts.", "duration_ms": 2200},
    ],
}

# Planner output (conceptual)
visual_segments = [
    {
        "section": "hook",
        "prompt": "close-up octopus underwater, dramatic reveal, vertical",
        "duration_ms": 3500,
        "provider": "stock",
    },
    {
        "section": "body",
        "prompt": "octopus moving with tentacles exploring reef, vertical",
        "duration_ms": 4000,
        "provider": "stock",
    },
    {
        "section": "cta",
        "prompt": "clean ocean background for end card, vertical",
        "duration_ms": 2200,
        "provider": "fallback",
    },
]

# Tool output (conceptual)
out = {
    **state,
    "visual_assets": visual_segments,
    "image_paths": [
        "/storage/job-42/visual_0.mp4",
        "/storage/job-42/visual_1.mp4",
        "/storage/job-42/visual_2.mp4",
    ],
}
```

#### When it is attractive

- cleanest long-term architecture for this repo
- directly compatible with future stock + AI + local sources
- naturally leverages `audio_segments`
- keeps deterministic degraded mode via a fallback provider
- easiest to test in isolation by injecting fake providers

#### Limits

- more design work than Solution 1
- requires a stronger output contract than a raw `list[str]`
- likely implies later updates to `VideoAssemblyTool`

---

### Solution 3 — Graph-like visual orchestration / multi-agent workflow

#### Description

Build the visual stage as a richer workflow with multiple internal nodes, for example:

- prompt generation node
- provider selection node
- retrieval / generation node
- normalization node
- validation / retry node

This could be implemented with LCEL composition or eventually with LangGraph if branching becomes complex.

The main idea is to optimize for advanced future features from day one:

- retry on poor stock matches
- mix image and video assets dynamically
- add ranking / quality scoring
- human review later

#### Example

```python
visual_graph = (
        PromptPlanningNode()
        | ProviderSelectionNode()
        | AssetFetchNode()
        | NormalizeNode()
        | ValidateNode()
)

# Conceptual behavior
# 1. derive prompts from hook/body/cta
# 2. try stock provider
# 3. retry with fallback provider if no usable asset
# 4. normalize to 9:16 local clip
# 5. emit validated visual manifest for assembly
```

#### When it is attractive

- best for very advanced future workflows
- supports branching, retries, scoring, and later human review
- aligns with `AGENTS.md` guidance that complex conditional logic can move toward LangGraph

#### Limits

- over-engineered for the current repository state
- highest implementation complexity
- hardest to introduce cleanly before the visual contract is stabilized
- adds mental overhead before the basic provider abstraction exists

---

## 5. Comparison criteria & Summary Table

### Comparison criteria

The solutions were compared using the criteria that matter most for this repository:

1. **Fit with current LCEL pipeline** — how naturally it fits `PipelineTool` + `PipelineState`
2. **Implementation complexity** — how much design and code it requires now
3. **Extensibility** — how well it supports future stock / AI / local providers
4. **Timing alignment quality** — how well it can use `audio_segments` / `audio_duration_ms`
5. **Degraded mode quality** — how cleanly it supports deterministic fallback without API keys
6. **Downstream usability** — how useful the output is for `VideoAssemblyTool` and future tools
7. **Testability** — how easy it is to unit test without network or ffmpeg dependencies everywhere
8. **Operational clarity** — how easy it is to reason about logs, failures, and artifact persistence

### Summary Table

| Solution                        | Fit with current repo | Complexity | Extensibility | Timing alignment | Degraded mode | Downstream usability | Testability | Overall                        |
|---------------------------------|-----------------------|------------|---------------|------------------|---------------|----------------------|-------------|--------------------------------|
| **1. Minimal evolution**        | Excellent             | Low        | Low           | Medium-Low       | Good          | Medium-Low           | Medium      | Good short-term only           |
| **2. Provider-based planner**   | Excellent             | Medium     | High          | High             | Excellent     | High                 | High        | **Best balance**               |
| **3. Graph-like orchestration** | Medium                | High       | Very High     | Very High        | High          | Very High            | Medium      | Strong long-term, weak for now |

### Ranked solutions

1. **Solution 2 — Provider-based Visual Planner inside a dedicated `VisualTool`**
2. **Solution 1 — Minimal evolution of the current `VisualTool`**
3. **Solution 3 — Graph-like visual orchestration / multi-agent workflow**

### Key differences

- **Solution 1** optimizes for speed of delivery.
- **Solution 2** optimizes for clean architecture with practical implementation scope.
- **Solution 3** optimizes for a future state that the repository is not ready to justify yet.

---

## 6. Chosen solution

### Chosen approach

**Solution 2 — Provider-based Visual Planner inside a dedicated `VisualTool`**

### Why this is the best fit

This solution best respects the existing Shorts Factory architecture while solving the real shortcomings of the current
visual stage.

It fits because:

- the pipeline still exposes one public node: `VisualTool()`
- internal complexity is handled through composition, not inheritance-heavy design
- it can reuse `audio_segments` from `VoiceTool` for alignment
- it supports multiple providers without turning the tool into a giant conditional block
- it preserves mandatory degraded mode via a deterministic fallback provider
- it sets up a better contract for the later `VideoAssemblyTool` and subtitle alignment work

### Proposed high-level architecture

Recommended internal components:

- `VisualTool`
    - public pipeline tool
    - reads `PipelineState`
    - invokes the planner
    - invokes one provider per planned segment
    - persists assets via storage
    - returns enriched immutable state
- `VisualPlanner`
    - turns `script` and optional voice metadata into a segment plan
    - uses rule-based planning first
    - may optionally use LCEL/LLM assistance later for prompt phrasing only
- `VisualProvider`
    - interface / protocol for asset resolution
    - implementations may include:
        - `PexelsVisualProvider`
        - `PixabayVisualProvider`
        - `LocalLibraryVisualProvider`
        - `FallbackVisualProvider`
- `VisualNormalizer`
    - validates that each asset exists
    - converts assets to consistent local formats and vertical aspect ratio
    - ensures outputs are directly consumable by ffmpeg assembly

### Recommended future state contract

For the actual implementation phase, the cleanest contract is to promote visuals to a first-class state field such as:

- `visual_assets: list[VisualAsset]`

Where each item includes at least:

- `section`
- `source_type`
- `provider`
- `prompt`
- `path`
- `duration_ms`
- `start_ms`
- `end_ms`
- `width`
- `height`

Then `VideoAssemblyTool` should consume `visual_assets` rather than relying only on `image_paths`.

### Why not the other options

- **Solution 1** would likely have to be redesigned again as soon as a second provider or richer timing model is added.
- **Solution 3** is architecturally interesting, but too heavy before the base planning/provider contract is stable.

---

## 7. Notes

### Important observations from the current repo

1. `image_paths` is a misleading name for the current visual output because the repo actually stores `.mp4` clips.
2. `VoiceTool` already provides most of the metadata needed for time-aligned visuals; the visual stage should exploit
   that instead of ignoring it.
3. The current `VisualTool` uses only `script["title"]`, which is too weak for visually coherent storytelling.
4. The project rules strongly favor deterministic fallbacks, so a fallback visual provider is not optional.
5. The planner should be mostly deterministic in V1; LLM assistance should be optional and limited to prompt refinement,
   not core control flow.

### Assumptions used in this document

- The immediate task is **analysis only**, not implementation.
- The actual target repository is **Shorts Factory**, not the unrelated MAS/NiceGUI project described by the external
  prompt.
- Future implementation may modernize the visual output contract instead of preserving `image_paths` as the only state
  field.

### Suggested implementation bias for the next phase

Prefer a **rule-based planner first**, with optional LCEL prompt enrichment later.

That keeps:

- tests stable
- degraded mode deterministic
- provider behavior observable
- implementation complexity under control

---

## 8. Ask clarification on unclear topic

### Question 1

The request references the external `project-sma` prompt, but the active workspace and local prompt clearly target
Shorts Factory. Should future phases continue using the **Shorts Factory interpretation**?

Answer: only Shorts Factory

### Question 2

For V1 of the Visual Agent, should the module support:

- stock **video clips only**, or
- a mix of **video clips + still images + local library assets** from day one?

Answer: a mix of video clips and still images, with a clear provider abstraction to add local library assets later.

### Question 3

Should timing be derived primarily from `audio_segments`, or is a simpler `hook/body/cta` equal-split approach
acceptable for the first implementation?

Answer: primarily from `audio_segments`, since that metadata is already available and provides better alignment. The
equal-split approach can be a fallback if `audio_segments` is missing or malformed.

### Question 4

Should the future public state contract replace `image_paths` with a richer `visual_assets` manifest, or should the
implementation keep `image_paths` as the main output despite its limitations?

Answer: the future public state contract should replace `image_paths` with a richer `visual_assets` manifest that
includes metadata for each asset. This provides a more robust and extensible foundation for downstream tools, even if it
requires updates to `VideoAssemblyTool` later.

### Question 5

Is optional LLM-assisted visual prompt generation acceptable in V1, or should the first implementation remain fully
deterministic and provider-driven?

Answer: Remaining fully deterministic and provider-driven in V1 is preferable to keep tests stable and behavior
predictable. LLM-assisted prompt generation can be added in a later iteration once the base architecture is solid.

