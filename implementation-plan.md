# Phase 1 Plan — Voice Generation (TTS) Module

## 1. Description of the problem

Shorts Factory is an LCEL pipeline where each step is a `Runnable[PipelineState, PipelineState]`. The second stage,
`VoiceTool`, is responsible for transforming the structured script produced by `ScriptChain` into an audio asset that
downstream steps can reuse.

Today, the implementation in `app/tools/voice_tool.py` is intentionally minimal:

- it concatenates `hook`, `body`, and `cta` into one text string,
- it calls ElevenLabs directly over HTTP when `ELEVENLABS_API_KEY` is configured,
- it falls back to ffmpeg-generated silence when no TTS API key is available,
- it stores one deterministic asset at `job_id/voice.mp3`,
- it returns only `audio_path` in `PipelineState`.

That baseline keeps the pipeline runnable, but it is too narrow for the next stage of the project. The voice module now
needs a design that stays simple while becoming easier to extend and safer to integrate with future features such as:

- multiple TTS providers,
- configurable voice parameters,
- optional timing metadata for subtitles and scene pacing,
- deterministic, testable degraded mode,
- clearer separation between provider logic, script normalization, and asset persistence.

### Repository-specific source note

The external planning prompt refers to `project.md` and `docs/features/`, but neither exists in this workspace. For this
plan, the authoritative sources are:

- `README.md`
- `AGENTS.md`
- `brainstorming.md`
- current implementation files under `app/`
- existing tests under `tests/`

---

## 2. Description of the chosen solution

## Selected solution

The chosen direction from `brainstorming.md` is:

**Provider abstraction + segment renderer + optional alignment metadata**

### Detailed solution description

The implementation should keep `VoiceTool` as the only pipeline-facing `PipelineTool`, while moving the internal TTS
concerns into smaller, testable building blocks.

The target structure is:

1. **`VoiceTool` remains the pipeline stage**
    - Reads `job_id` and `script` from `PipelineState`
    - Loads settings lazily via `get_settings()`
    - Chooses the active provider based on configuration
    - Delegates rendering to a dedicated renderer/service layer
    - Saves generated artifacts through `get_storage()`
    - Returns a new enriched state dict without mutating the input

2. **A provider contract encapsulates TTS backends**
    - Defines the minimum interface required to synthesize text
    - Returns audio bytes plus optional metadata
    - Allows a cloud provider such as ElevenLabs and a local degraded fallback to share one contract

3. **A script renderer owns normalization and chunking**
    - Accepts the structured script object
    - Preserves semantic sections (`hook`, `body`, `cta`)
    - Normalizes punctuation / whitespace for speech quality
    - Splits large text into renderable chunks if necessary
    - Produces a final merged audio asset and segment metadata

4. **Fallback remains first-class**
    - Degraded mode should stay silent for v1
    - It must still generate a valid audio file and keep the pipeline end-to-end runnable
    - The fallback should live behind the same provider abstraction so the pipeline surface stays unchanged

### Chosen output contract for implementation

For the first implementation, the contract should evolve conservatively:

- keep `audio_path` as the only required output,
- add optional metadata only when it can be produced cleanly,
- prefer segment-level metadata over word-level timestamps for v1.

The most likely optional additions are:

- `audio_segments`
- `audio_duration_ms`
- `voice_provider`
- `voice_id`

### Research notes relevant to implementation

From the earlier research and current repository constraints:

1. **ElevenLabs** offers a `with-timestamps` endpoint that can provide audio plus character-level timing. This means the
   provider layer should be designed so provider-native timing can be surfaced later without redesigning `VoiceTool`.
2. **LangChain / LCEL** supports keeping application logic in dedicated classes while exposing only a clean `Runnable`
   boundary, which aligns with the current `PipelineTool` model.
3. **Coqui TTS** remains a future candidate for a local provider, which reinforces the value of a provider contract now,
   even if only one remote provider plus one fallback provider are implemented initially.
4. **Project conventions in `AGENTS.md`** require lazy initialization, no state mutation, deterministic storage keys,
   structured logging, and degraded-mode behavior. The chosen solution naturally supports all of those constraints.

### Notes gathered from `brainstorming.md` that should drive implementation

- Keep provider selection configuration-driven for v1.
- Keep degraded mode silent for v1.
- Support segment-level timing before word-level timing.
- Normalize and chunk text, but preserve traceability back to `hook`, `body`, and `cta`.
- Avoid adding heavy alignment dependencies in the first iteration.

---

## 3. Detailed implementation plan

### Phase A — Define the internal voice-domain contract

- [x] Create a small voice-domain model inside `app/` for the implementation, such as typed structures or dataclasses
  representing voice configuration, rendered audio, and segment metadata.
- [x] Decide the minimum provider contract for v1 (for example: synthesize text, return audio bytes, optionally return
  metadata).
- [x] Define how script sections (`hook`, `body`, `cta`) map to renderable segments while preserving original section
  identity.
- [x] Decide the initial optional `PipelineState` additions needed for v1, keeping `audio_path` required and everything
  else optional.
- [x] Document deterministic storage key rules for audio and optional metadata artifacts so the implementation remains
  idempotent by `job_id`.
- [x] Run all tests and fix failing tests.

### Phase B — Extend configuration and state safely

- [x] Update `app/chains/state.py` to include any optional voice-related output fields selected for v1, such as
  `audio_segments`, `audio_duration_ms`, `voice_provider`, or `voice_id`.
- [x] Extend `app/core/config.py` with any new voice settings required by the chosen design, keeping them
  configuration-driven and default-safe.
- [x] Review `.env.example` requirements and identify any new public environment variables that must be documented once
  implementation starts.
- [x] Verify that configuration defaults preserve current degraded-mode behavior when no TTS credentials are set.
- [x] Run all tests and fix failing tests.

### Phase C — Introduce provider abstraction

- [x] Add a dedicated provider abstraction under `app/services/` or another appropriate internal module, following the
  repository guidance for wrappers around external providers.
- [x] Implement an ElevenLabs provider class that encapsulates HTTP request construction, response validation, and audio
  extraction, rather than leaving that logic directly inside `VoiceTool`.
- [x] Implement a fallback provider class that generates valid silent audio while preserving the current “pipeline
  always runs” guarantee.
- [x] Make provider initialization lazy so tests can instantiate `VoiceTool` without network dependencies or global side
  effects.
- [x] Standardize provider outputs so `VoiceTool` does not need provider-specific branching beyond provider selection.
- [x] Run all tests and fix failing tests.

### Phase D — Introduce the script voice renderer

- [x] Create a `ScriptVoiceRenderer`-style component that accepts the structured script and a provider instance.
- [x] Implement text normalization rules for `hook`, `body`, and `cta` that improve speech cadence without losing
  traceability.
- [x] Add chunking behavior for long text sections, especially `body`, while preserving a mapping from source section to
  rendered chunk.
- [x] Define how rendered chunks are recombined into one final audio asset for storage.
- [x] Define the v1 segment metadata format so downstream tools can reason about section timing later.
- [x] Keep the first iteration focused on segment-level metadata and explicitly defer word-level alignment.
- [x] Run all tests and fix failing tests.

### Phase E — Refactor `VoiceTool` around the new internals

- [x] Refactor `app/tools/voice_tool.py` so it becomes a thin orchestration layer: read state, choose provider, delegate
  rendering, store artifacts, return enriched state.
- [x] Remove provider-specific HTTP and fallback-generation details from `VoiceTool` where they are replaced by
  dedicated internal classes.
- [x] Preserve the `PipelineTool` contract, including no in-place mutation, structured logging, and exception
  propagation.
- [x] Preserve deterministic output keys such as `job_id/voice.mp3`, and add deterministic metadata keys if optional
  artifacts are written.
- [x] Ensure the refactor does not require any change to `app/chains/pipeline.py` unless new imports or organization
  make that necessary.
- [x] Run all tests and fix failing tests.

### Phase F — Add and adapt automated tests

- [x] Add a dedicated unit test module for `VoiceTool` behavior if none exists yet, covering degraded mode, provider
  selection, deterministic storage paths, and non-mutation of input state.
- [x] Add unit tests for the provider abstraction using stubs or monkeypatched HTTP calls rather than real network
  requests.
- [x] Add unit tests for the renderer, especially normalization, chunking, segment mapping, and metadata output shape.
- [x] Adapt `tests/test_pipeline.py` only if the public pipeline contract changes; otherwise preserve it as a smoke test
  proving composition still works.
- [x] Review whether any tests need to validate new optional state fields without making them mandatory for unrelated
  pipeline stages.
- [x] If method signatures or module locations change, update imports in affected tests to keep the suite consistent
  with the refactor.
- [x] Run all tests and fix failing tests.

### Phase G — Documentation and project consistency

- [x] Update `README.md` to describe the new voice architecture, configuration options, and degraded-mode behavior once
  implementation is complete.
- [x] Update `.env.example` with any new public voice-related settings.
- [x] Update `AGENTS.md` if the voice agent contract or recommended extension approach changes materially.
- [x] Verify that the final design still follows the repository rules: no direct unmanaged I/O, no hardcoded secrets, no
  circular dependency, no state mutation, and degraded mode remains mandatory.
- [x] Run all tests and fix failing tests.

### Phase H — Final validation checklist before merge

- [x] Run the full test suite with `pytest` and fix any failing tests.
- [x] Run `ruff check app/` and fix any lint issues.
- [x] Perform one manual smoke run of the pipeline in degraded mode to confirm that `VoiceTool` still produces a usable
  audio artifact without external credentials.
- [x] Perform one provider-enabled smoke path with stubbed or controlled configuration if possible, without baking
  secrets into code or tests.
- [x] Review logs to confirm structured events still include useful `job_id` / tool context.

---

## 4. Notes

- This plan intentionally adapts the external prompt to the actual `shorts-factory` repository. There is no `project.md`
  or `docs/features/` directory here, so the plan uses repository-local sources instead.
- The repository currently declares `requires-python = ">=3.10"` in `pyproject.toml`, so implementation steps should
  respect that baseline unless the project explicitly upgrades later.
- The current README claims TTS providers are swappable, but the present code is still provider-specific. This refactor
  is the right place to make that claim truly accurate.
- The first implementation should avoid introducing heavy forced-alignment dependencies such as WhisperX unless subtitle
  precision becomes a confirmed requirement.
- Because `SubtitleTool` and later stages currently consume `audio_path` rather than voice metadata, optional fields
  should be introduced in a way that does not create unnecessary coupling.
- The fallback generator currently uses ffmpeg and a temporary file. During implementation, pay special attention to
  keeping the storage contract and cleanup behavior safe and testable.
- If public configuration keys are added, the implementation must also update documentation and environment examples as
  required by `AGENTS.md`.

---

## 5. Ask clarification on unclear topic

### Question 1

Which optional `PipelineState` fields do you want implemented in the first pass besides `audio_path`?

Answer: In the first pass, implement `audio_segments`, `voice_provider`, and `voice_id` as optional fields. Those three
fields are the most useful immediately because they improve observability and future subtitle/video timing integration
without forcing downstream tools to depend on heavy metadata. `audio_duration_ms` can be added in the same pass only if
it can be derived reliably without introducing extra complexity or new heavy dependencies.

### Question 2

Do you want the first provider abstraction to support only ElevenLabs + silent fallback, or should the initial code
already include a placeholder local-provider implementation for future expansion?

Answer: The first provider abstraction should support only ElevenLabs plus the silent fallback provider. That gives the
project a real abstraction with immediate value while keeping the initial scope small and testable. A placeholder local
provider is not necessary for v1 because it would add maintenance surface without providing a production benefit yet.

### Question 3

Should segment metadata be persisted to storage as a separate JSON artifact in v1, or kept only in-memory in
`PipelineState`?

Answer: Persist segment metadata as a separate JSON artifact in v1, and also expose the parsed segment metadata in
`PipelineState` when convenient. Persisting it makes the output reproducible, keeps the artifacts tied to `job_id`, and
gives downstream tools a stable handoff point without requiring them to regenerate metadata from memory.

### Question 4

How aggressive should text normalization be for the first implementation: whitespace and punctuation cleanup only, or
also light sentence rewriting for speech cadence?

Answer: For the first implementation, normalization should be limited to whitespace cleanup, punctuation cleanup, and
safe chunk preparation. It should not rewrite sentence meaning or introduce stylistic paraphrasing. That keeps the
system deterministic, easier to test, and faithful to the validated script generated upstream.

### Question 5

Should the first implementation prioritize keeping dependencies minimal, even if that means postponing richer audio
inspection such as accurate duration calculation until a later phase?

Answer: Yes. The first implementation should prioritize minimal dependencies, even if that means deferring richer audio
inspection features. If `audio_duration_ms` can be estimated or derived from existing provider metadata or simple
tooling already available in the stack, it is acceptable to include; otherwise it should be postponed to a later phase
rather than pulling in heavy audio-processing dependencies too early.

