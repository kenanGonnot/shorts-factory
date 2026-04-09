# Phase 0 Analysis — Voice Generation (TTS) Module

## 1. Description of the problem

The next step to design in **Shorts Factory** is the `VoiceTool`, the second stage of the LCEL pipeline:

`topic → ScriptChain → VoiceTool → VisualTool → VideoAssemblyTool → SubtitleTool → PublishingTool`

This module consumes the structured script produced by `ScriptChain` and must generate audio that is:

- natural enough for short-form social video,
- deterministic enough for automated downstream processing,
- configurable enough to support different voices and speaking styles,
- reusable by future steps such as subtitle generation and video assembly,
- resilient enough to keep the pipeline working in degraded mode when no external API key is available.

From the current repository state:

- `app/tools/voice_tool.py` already synthesizes one MP3 file and stores it in the configured storage backend;
- `PipelineState` currently exposes `audio_path` only;
- the contribution rules in `AGENTS.md` require idempotency when possible, no in-place mutation of state, no direct
  unmanaged disk I/O, structured logging, and a degraded fallback that still allows the full pipeline to run end-to-end.

The design challenge is therefore not only “generate speech”, but also define a **clean contract** for future growth:
multiple TTS providers, optional timing metadata, stable storage keys, and compatibility with the existing LangChain
`Runnable` pipeline.

---

## 2. Research summary

### Repository findings

1. `VoiceTool` is currently a single class inheriting from `PipelineTool` and writing `audio_path` back into
   `PipelineState`.
2. The current implementation concatenates `hook`, `body`, and `cta` into one text payload, uses ElevenLabs over HTTP
   when configured, and falls back to ffmpeg-generated silence in development mode.
3. `PipelineState` does not yet expose timing metadata, voice configuration, or provider metadata.
4. Project conventions strongly favor:
    - simple dedicated classes,
    - lazy initialization,
    - storage abstraction via `get_storage()`,
    - degraded-mode fallbacks,
    - LCEL composition over ad-hoc orchestration.

### External research highlights

1. **ElevenLabs TTS docs** expose a `with-timestamps` endpoint that returns generated audio together with precise
   character-level timing metadata. This is directly relevant for subtitles, scene timing, and future alignment work.
2. **ElevenLabs best-practices docs** emphasize that delivery quality improves when text is normalized and chunked
   sensibly, and when punctuation is used intentionally to shape cadence, pauses, and emphasis.
3. **Coqui TTS** provides an open-source local TTS path that is attractive for privacy, offline development, and future
   provider independence, but it increases operational complexity and local runtime cost.
4. **WhisperX** is widely used for word-level timestamps and post-hoc alignment. It is a strong fallback when the chosen
   TTS provider does not expose alignment metadata or when downstream subtitle quality needs to be normalized across
   providers.
5. **ffmpeg `anullsrc`** remains a valid degraded-mode mechanism for generating silence and keeping the pipeline
   runnable even without cloud credentials.

### Practical implications from the research

- If we want the fastest path to aligned audio, provider-native timestamps are the easiest option.
- If we want long-term flexibility, we should not couple the entire design to one TTS API response shape.
- If we want high subtitle quality across providers, post-generation forced alignment is the most robust but also the
  heaviest solution.
- The best design should preserve the current simple `VoiceTool` pipeline contract while allowing optional richer
  outputs later.

---

## 3. Thinking process

I evaluated the problem from the perspective of the current repository rather than inventing a separate subsystem.

### Core constraints

1. The module must fit the existing `PipelineTool` contract.
2. The pipeline must still run without any API key.
3. The design should support richer metadata for future subtitle and edit timing needs.
4. The implementation should stay testable without real provider calls.
5. The solution should remain easy to extend without turning `VoiceTool` into a large, provider-specific class.

### Main architectural questions

1. Should audio be generated in one pass or segment-by-segment?
2. Should alignment come from the TTS provider, from a second alignment pass, or be omitted for v1?
3. Should provider support live inside `VoiceTool` or behind a small provider abstraction?
4. How much extra metadata should be added to `PipelineState` immediately?

### Design direction

The current codebase is simple and intentionally pragmatic. That suggests avoiding a heavy framework inside the TTS
stage. At the same time, the project roadmap clearly benefits from a stable voice-generation contract.

That leads to three realistic options:

- a minimal provider-coupled solution,
- a balanced provider abstraction with segment rendering,
- a more advanced two-pass render-and-align system.

---

## 4. Solutions

### Solution 1 — Minimal remote-first `VoiceTool` using ElevenLabs timestamps

#### Description

Keep the architecture close to the current implementation:

- `VoiceTool` remains the only public class for the stage;
- the tool concatenates the script into one normalized text payload;
- ElevenLabs stays the primary provider;
- when configured, the tool calls the provider endpoint that returns both audio and timing metadata;
- when not configured, the tool falls back to ffmpeg-generated silence;
- optional metadata such as provider name, voice id, duration estimate, and timestamp file path can be added to the
  state later.

This is the simplest path and offers immediate value because it leverages provider-native timing support.

#### Example

```python
state = {
    "job_id": "job-42",
    "script": {
        "title": "Coffee facts",
        "hook": "Coffee can improve reaction time.",
        "body": "Caffeine blocks adenosine and helps you feel alert.",
        "cta": "Follow for more science shorts.",
        "tags": ["coffee", "science"],
    },
}

# Conceptual output
{
    **state,
    "audio_path": "storage/job-42/voice.mp3",
    "voice_provider": "elevenlabs",
    "voice_timestamps_path": "storage/job-42/voice_alignment.json",
}
```

#### Pros

- Fastest to implement.
- Fits the current repository style.
- Minimal number of moving parts.
- Timestamps are available without a second pipeline pass.

#### Cons

- Strong coupling to ElevenLabs response semantics.
- Harder to support multiple providers cleanly.
- Chunking, normalization, and alignment logic can become tangled inside one class.
- Less future-proof if the team wants local/offline synthesis.

---

### Solution 2 — Provider abstraction + segment renderer + optional alignment metadata

#### Description

Introduce a small TTS service layer while keeping `VoiceTool` as the pipeline-facing class:

- `VoiceTool` remains the LangChain stage;
- it delegates synthesis to a dedicated provider interface such as `TTSProvider`;
- a `ScriptVoiceRenderer` prepares segments from `hook`, `body`, and `cta`;
- each segment is synthesized individually or in controlled chunks;
- the renderer merges audio and emits segment-level metadata;
- providers can expose native alignment when available, while the common contract stays provider-agnostic;
- degraded mode still uses a silent or simple generated fallback provider.

This creates a stable architecture without over-engineering the pipeline surface.

#### Example

```python
class TTSProvider(Protocol):
    def synthesize(self, text: str, voice: VoiceConfig) -> AudioChunk:
        ...


class ScriptVoiceRenderer:
    def render(self, script: Script, provider: TTSProvider) -> RenderedAudio:
        # hook, body, cta -> segments -> audio + metadata
        ...


class VoiceTool(PipelineTool):
    name = "VoiceTool"

    def run(self, state: PipelineState) -> PipelineState:
        rendered = renderer.render(state["script"], provider)
        return {**state, "audio_path": rendered.audio_path}
```

Possible segment metadata:

```json
[
  {
    "segment": "hook",
    "start_ms": 0,
    "end_ms": 1900
  },
  {
    "segment": "body",
    "start_ms": 1900,
    "end_ms": 6400
  },
  {
    "segment": "cta",
    "start_ms": 6400,
    "end_ms": 7900
  }
]
```

#### Pros

- Best balance between simplicity and extensibility.
- Makes multiple providers realistic without changing pipeline composition.
- Keeps `VoiceTool` small and testable.
- Segment metadata is very useful for visuals, subtitle timing, and analytics.
- Preserves degraded mode through a dedicated fallback provider.

#### Cons

- Slightly more design work than a single-class solution.
- Requires a clear minimal contract for provider outputs.
- Audio concatenation and metadata merging must be handled carefully.

---

### Solution 3 — Provider-agnostic render first, then forced alignment pass

#### Description

Separate speech synthesis from alignment entirely:

1. generate audio with any provider,
2. run a second alignment step using a tool such as WhisperX,
3. normalize word/segment timestamps into a provider-independent asset format.

This architecture is the strongest if subtitle precision and provider neutrality are the highest priorities.

#### Example

```python
audio_asset = tts_provider.synthesize(full_text, voice_config)
alignment = whisperx_align(audio_asset.path, transcript=full_text)

result = {
    "audio_path": audio_asset.path,
    "alignment_path": alignment.path,
    "alignment_source": "whisperx",
}
```

#### Pros

- Best provider independence.
- Word-level alignment can be normalized across all providers.
- Excellent base for subtitles and edit timing.
- Avoids provider lock-in around metadata formats.

#### Cons

- Highest implementation and operational complexity.
- Adds heavy runtime dependencies and slower processing.
- Harder to keep degraded mode lightweight.
- More moving parts to test and containerize.

---

## 5. Comparison criteria & Summary Table

### Comparison criteria

I used the following criteria to compare the options:

1. **Fit with current repository architecture** — does it work naturally with `PipelineTool`, storage abstraction, and
   `PipelineState`?
2. **Implementation complexity** — how much code and operational change is required?
3. **Extensibility** — how easily can we add more providers or richer configuration?
4. **Alignment quality** — how well does it support subtitles and time-based video assembly?
5. **Degraded-mode support** — how easily can the pipeline still run without cloud credentials?
6. **Testing simplicity** — can the behavior be validated with deterministic unit tests?
7. **Operational footprint** — how expensive is it to run locally and in CI/CD?

### Summary Table

| Solution                                       | Architecture fit | Complexity | Extensibility |                                           Alignment quality | Degraded mode | Testing | Operational footprint | Summary                                                          |
|------------------------------------------------|------------------|-----------:|--------------:|------------------------------------------------------------:|--------------:|--------:|----------------------:|------------------------------------------------------------------|
| **1. Minimal remote-first**                    | Excellent        |        Low |    Medium-Low |               Medium-High if ElevenLabs timestamps are used |          High |    High |                   Low | Best for a fast v1 but tied to one provider                      |
| **2. Provider abstraction + segment renderer** | Excellent        |     Medium |          High | High at segment level, with optional provider-native timing |          High |    High |                Medium | Best overall balance for this project                            |
| **3. Render then forced alignment**            | Medium           |       High |     Very High |                                                   Very High |        Medium |  Medium |                  High | Strongest long-term alignment model, but heavy for current stage |

### Ranked solutions

1. **Solution 2 — Provider abstraction + segment renderer + optional alignment metadata**
2. **Solution 1 — Minimal remote-first `VoiceTool` using ElevenLabs timestamps**
3. **Solution 3 — Provider-agnostic render first, then forced alignment pass**

---

## 6. Choosen solution

### Selected option

**Solution 2 — Provider abstraction + segment renderer + optional alignment metadata**

### Why this is the best fit

This option matches the project’s current architecture and future ambitions better than the alternatives.

It keeps the public pipeline contract simple:

- the pipeline still uses one `VoiceTool()` stage,
- the stage still returns enriched `PipelineState`,
- storage and fallback behavior remain centralized and testable.

At the same time, it avoids the biggest long-term weakness of the current implementation: provider-specific logic
growing directly inside `VoiceTool`.

### Recommended design direction for implementation

When implementation starts, the design should likely evolve toward these responsibilities:

1. **`VoiceTool`**
    - reads `script` and `job_id` from `PipelineState`,
    - loads configuration,
    - selects the provider lazily,
    - delegates rendering,
    - writes output paths and optional metadata into a new state dict.

2. **`TTSProvider` contract**
    - accepts normalized text plus voice settings,
    - returns audio bytes and optional timing metadata,
    - allows multiple backends such as ElevenLabs, PlayHT, or Coqui.

3. **`ScriptVoiceRenderer`**
    - turns structured script into renderable segments,
    - enforces text normalization and chunking rules,
    - merges segment outputs into one final asset,
    - produces segment-level metadata for downstream use.

4. **Fallback provider**
    - guarantees degraded-mode execution,
    - produces at minimum a valid audio file,
    - can later evolve from silence-only to a lightweight local voice if desired.

### Recommended output contract evolution

Keep `audio_path` as the primary required output, then consider adding optional keys such as:

- `audio_metadata_path`
- `audio_segments`
- `voice_provider`
- `voice_id`
- `audio_duration_ms`

This respects the current pipeline while preparing for subtitles, visual synchronization, and analytics.

---

## 7. Notes

- I treated the in-repository `Shorts Factory` context as authoritative because the attached external prompt path
  targets a different project domain. I still followed the same phase-0 workflow: analyze, research, compare three
  solutions, and choose one.
- The repository currently targets **Python >=3.10** in `pyproject.toml`, even though the phase-0 prompt mentions Python
  3.11+. Since this phase is analysis-only, the design intentionally stays compatible with the repository’s actual
  baseline.
- The current `VoiceTool` already satisfies the degraded-mode philosophy, but it does not yet expose alignment artifacts
  or provider-neutral abstractions.
- Segment-level metadata is likely more useful than only a raw full-text timestamp dump because later tools can reason
  directly about `hook`, `body`, and `cta` boundaries.
- A full forced-alignment stack is attractive, but it should probably be deferred until subtitle accuracy becomes a
  demonstrated bottleneck.
- Implementation should remain idempotent by storing deterministic keys such as `job_id/voice.mp3` and
  `job_id/voice_alignment.json`.

---

## 8. Ask clarification on unclear topic

### Question 1

Should the first implementation of the voice module keep `PipelineState` minimal with only `audio_path`, or should it
immediately add optional timing metadata fields for subtitles and video timing?

Answer: Keep `audio_path` as the only required field for the first implementation, but add optional timing metadata
immediately if it can be produced cleanly without complicating the core contract. My recommendation is to add optional
segment-oriented fields such as `audio_segments` and `audio_duration_ms`, while deferring heavier or more
provider-specific metadata until a downstream consumer actually requires it.

### Question 2

Do you want provider selection to be strictly configuration-driven for v1, or should the design already support per-job
voice/provider overrides inside `PipelineState`?

Answer: For v1, provider selection should be configuration-driven. This keeps the first implementation simpler, easier
to test, and more consistent with the current repository style. Per-job overrides can be added later, but only once
there is a concrete product need and a clear `PipelineState` contract for passing voice preferences safely through the
pipeline.

### Question 3

Is degraded mode expected to remain silent audio only, or would you prefer a lightweight local spoken fallback once the
architecture is in place?

Answer: Degraded mode should remain silent audio for the first implementation. It is the lowest-risk fallback, fully
aligned with the current project conventions, and ensures the pipeline always runs end-to-end. Once the provider
abstraction is in place, a lightweight spoken local fallback can be introduced later behind the same interface without
changing the pipeline surface.

### Question 4

For downstream consumers, is segment-level timing (`hook`, `body`, `cta`) sufficient, or do you expect word-level
timestamps from the very first implementation?

Answer: Segment-level timing is sufficient for the first implementation. It maps naturally to the current structured
script shape (`hook`, `body`, `cta`) and gives downstream tools enough information to improve subtitle placement and
visual pacing. Word-level timestamps should be treated as a future enhancement when subtitle precision becomes an
explicit requirement.

### Question 5

Should the voice module normalize and chunk long body text automatically, even if that means the generated audio no
longer maps one-to-one to the original raw strings?

Answer: Yes, the voice module should normalize and chunk long body text automatically, but it should do so in a
controlled way that preserves traceability. The renderer should keep a mapping between original script sections and
rendered chunks so downstream components can still relate timing metadata back to `hook`, `body`, and `cta` even if the
spoken audio is optimized for cadence and provider limits.

