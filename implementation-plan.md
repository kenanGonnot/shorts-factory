# Implementation Plan — Script Generation Module for Shorts Factory

## 1. Description of the problem

Shorts Factory needs to replace its minimal script-generation entry point with a more robust, implementation-ready
module that produces structured script data for the rest of the LCEL pipeline.

Today, `app/chains/script_chain.py` uses a lightweight `prompt | ChatOpenAI | JsonOutputParser` flow wrapped in a
`RunnableLambda`. That shape is simple, but it leaves several phase-1 issues unresolved:

- the returned structure is only loosely enforced
- content constraints are described in prompt text instead of centralized validation
- the current logic is not encapsulated in a dedicated class
- degraded-mode / no-key behavior is not clearly designed at the script stage
- the future script contract may need to evolve beyond the current `body: str`

The repository context from `AGENTS.md`, `README.md`, and `brainstorming.md` makes the target clear:

- the script module is the **first agent** in a larger end-to-end pipeline
- it must remain compatible with **LangChain LCEL**
- it must produce **stable structured output** for downstream tools
- it should be **simple, modular, and testable**
- it should follow the project’s non-mutation and degraded-mode rules
- it should be ready for future downstream automation such as subtitles, visuals, and publishing

There is also one important repo reality to account for in the plan:

- `docs/features/` does **not** exist in this workspace, so there is no additional feature document to anchor the
  implementation plan

---

## 2. Description of the chosen solution

### Chosen solution

The selected direction from `brainstorming.md` is:

**A dedicated `ScriptGenerator` class with schema-driven structured output.**

### What this solution means in practice

Instead of keeping script generation as a mostly inline LCEL expression with post-hoc JSON parsing, the implementation
should introduce a dedicated class that owns the full script-generation lifecycle:

- prompt construction
- model initialization
- schema-driven output generation
- business validation
- fallback / no-key policy
- conversion to the final `PipelineState["script"]` payload
- Runnable-compatible integration with `build_pipeline()`

This approach keeps the external pipeline usage simple while making the internals much more reliable and testable.

### Research-backed implementation direction

Brief online research plus LangChain documentation strongly supports moving from free-form JSON parsing to schema-driven
structured output:

- LangChain’s current structured-output guidance recommends using `ChatOpenAI.with_structured_output(...)` with a *
  *Pydantic model** or JSON schema rather than depending only on raw JSON parsing.
- The documented `method="json_schema"` pattern is designed to return values that conform to the declared schema, which
  reduces parser fragility and makes validation more explicit.
- A validated schema object is a better fit for a pipeline that must hand structured data to multiple downstream
  automation steps.

For this repo, that suggests the following architectural direction:

1. define a schema model for script output
2. use `ChatOpenAI.with_structured_output(...)` where possible
3. keep business-rule validation inside the dedicated class instead of spreading it across prompt text and parsing code
4. return a plain Python structure that matches the project’s state contract
5. preserve a Runnable entry point so `build_pipeline()` remains simple

### Relevant notes gathered from `brainstorming.md`

The existing analysis and recorded answers in `brainstorming.md` add useful implementation constraints:

- prefer a **dedicated class** instead of more inline chain wiring
- keep the implementation **KISS** and avoid a multi-pass repair design in phase 1
- default output language appears to lean toward **English**, while still allowing topic-aware language handling if
  explicitly desired
- there is interest in a **more structured script body** for subtitles/editing later, likely moving beyond a single
  `body: str`
- there is interest in **optional metadata** such as estimated duration, pacing notes, or visual cues
- the fallback policy remains **unclear** because the answer recorded in `brainstorming.md` for the no-key case is
  ambiguous; this must be clarified before implementation is finalized

### Recommended implementation shape

A good phase-1 implementation should likely:

- introduce a dedicated `ScriptGenerator` class
- define a strong schema using Pydantic
- decide whether the public pipeline contract stays minimal or expands now to include structured lines and optional
  metadata
- remove the old parser-first flow instead of preserving legacy branches
- expose a Runnable adapter so the rest of the pipeline does not need to know the internals

---

## 3. A detailed implementation plan

### Proposed implementation sequence

- [x] Finalize the target script contract before editing code: phase 1 keeps the existing public payload with
  `title`, `hook`, `body`, `cta`, and `tags`, while richer validation stays internal to the generator.
  No-key behavior now uses a deterministic degraded-mode fallback instead of fail-fast.

- [x] Define the phase-1 schema design on paper inside the implementation work: `StructuredScript` is now the internal
  Pydantic validation model, and it maps back to the unchanged public `PipelineState["script"]` payload.

- [x] Run all tests and fix failing tests before starting the refactor so the baseline is known (`pytest` and
  `ruff check app/`). The Python environment was completed locally so the baseline commands now run in `.venv`.

- [x] Refactor the script-generation architecture by introducing a dedicated `ScriptGenerator` class in the
  script-generation surface area (either in `app/chains/script_chain.py` or a new adjacent module such as
  `app/chains/script_generator.py`) and move prompt building, model creation, invocation, validation, and state
  adaptation into that class.

- [x] Replace the current `JsonOutputParser`-centric path with schema-driven generation using
  `ChatOpenAI.with_structured_output(...)` and a Pydantic model, preferring `method="json_schema"` and strict schema
  validation where supported by the current LangChain/OpenAI integration.

- [x] Centralize business-rule validation inside the dedicated class: enforce field presence, non-empty text, tag shape,
  title limits, body/body-line constraints, and any duration or metadata rules chosen for phase 1.

- [x] Remove legacy script-generation logic that becomes redundant after the class-based implementation, instead of
  leaving old parsing branches in place.

- [x] Run all tests and fix failing tests after the refactor (`pytest` and `ruff check app/`).

- [x] Update `app/chains/state.py` to reflect the final chosen script contract for phase 1. The public contract remains
  minimal, and the type definitions now stay aligned with the runtime payload while using Python 3.10 native typing.

- [x] Update the exported script-chain entry point so the pipeline still composes as a
  single LCEL expression while delegating script-generation behavior to the new dedicated class.

- [x] No environment-variable or config-surface change was required, so `app/core/config.py` and `.env.example`
  remain unchanged. Public docs were updated where the runtime behavior changed.

- [x] Run all tests and fix failing tests after the state/pipeline integration step (`pytest` and `ruff check app/`).

- [x] Add focused unit tests for the new script-generation behavior under `tests/`, covering at minimum: successful
  structured generation, schema validation failures, deterministic no-key behavior or fail-fast behavior (depending on
  the final decision), language handling expectations, tag validation, and any richer body/metadata mapping introduced
  in phase 1.

- [x] Add or update tests for the Runnable/state adapter so it proves that `PipelineState` is enriched without in-place
  mutation and that the generated payload matches the declared script contract.

- [x] Keep `tests/test_pipeline.py` aligned with the unchanged public script contract and preserve the composition-only
  smoke-test role.

- [x] Add regression tests for whichever clarification-driven decisions are accepted from `brainstorming.md`, especially
  if the final design includes English-by-default behavior, same-language passthrough, optional metadata fields, or a
  richer script-body representation.

- [x] Run all tests and fix failing tests after the test-suite updates (`pytest` and `ruff check app/`).

- [x] Review the implementation against `AGENTS.md` rules: no state mutation, no hardcoded secrets, no unnecessary
  circular imports, lazy model/client initialization where relevant, and structured logging if any logging is added
  during the refactor.

- [x] If the refactor meaningfully changes the public script contract or agent behavior, update `AGENTS.md` and
  `README.md` so the repo documentation matches the new script-generation design.

- [x] Run all tests and fix failing tests one final time, then do a short manual smoke verification of the
  script-generation entry point in isolation.

### Unit tests likely to be impacted

The plan should assume impact in at least these areas:

- `tests/test_pipeline.py` smoke coverage
- new isolated unit tests for the dedicated script generator
- any future tests that depend on the exact shape of `state["script"]`

If the public contract changes from `body: str` to a richer shape, tests will need to be updated deliberately rather
than shimmed for backward compatibility.

---

## 4. Notes

- No `docs/features/` directory exists in this workspace, so the plan is based on repository code and the existing
  markdown guidance only.
- The current dependency set already includes the main tools needed for the chosen approach: `pydantic`, `langchain`,
  `langchain-core`, and `langchain-openai` are already present in `pyproject.toml`.
- Because the user requested that backward compatibility not be prioritized, the implementation can remove the old
  `JsonOutputParser` path instead of preserving parallel legacy behavior.
- The biggest open design decision is the public script contract for phase 1: either keep the current simple payload for
  minimal downstream disruption, or formally upgrade the pipeline state now to include body lines and optional metadata.
- The second biggest open decision is no-key behavior. `AGENTS.md` favors degraded mode, but the clarification recorded
  in `brainstorming.md` is ambiguous and may imply fail-fast. This must be resolved before implementation.
- The plan assumes a single-step generation flow, not a multi-pass repair system, because the chosen solution explicitly
  favored KISS over a heavier architecture.

---

## 5. Ask clarification on unclear topic

### Question 1

Should phase 1 keep the public script contract as the current minimal shape (`title`, `hook`, `body`, `cta`, `tags`), or
should we formally upgrade it now to include `body_lines` and optional metadata fields?

Answer: Keep the current minimal public contract for phase 1: `title`, `hook`, `body`, `cta`, and `tags`. This avoids
immediate downstream churn because `app/chains/state.py`, `tests/test_pipeline.py`, and `app/tools/subtitle_tool.py`
already depend on `body: str`. If richer structure is useful internally, the dedicated `ScriptGenerator` may use it
during validation and then map back to the current public payload. Formal `body_lines` and metadata fields should be
deferred to a later phase.

### Question 2

For the no-API-key case, should script generation follow the repository’s degraded-mode philosophy with a deterministic
fallback, or should it fail fast for this specific stage?

Answer: Follow the repository’s degraded-mode philosophy and provide a deterministic fallback. `AGENTS.md` explicitly
requires the pipeline to keep running end-to-end without API keys, so the script stage should not fail fast by default.
The fallback should generate a predictable, reusable script from the topic with the same public schema, making local
development and smoke testing reliable.

### Question 3

If English is the default output language, should a non-English topic automatically produce a matching non-English
script, or should the generator stay English-only unless a language is explicitly provided elsewhere?

Answer: A non-English topic should automatically produce a matching non-English script. English remains the default when
the topic is English or language is ambiguous, but the generator should follow the topic language when it is clearly
non-English. This keeps the interface simple because no new language field is required in `PipelineState` for phase 1.

### Question 4

If optional metadata is included, which fields are truly required for phase 1: `estimated_duration_seconds`,
`pacing_notes`, `visual_cues`, or none of them?

Answer: None of them are required for phase 1. The public pipeline payload should stay minimal, and any metadata
experimentation should remain optional and internal to the `ScriptGenerator`. If metadata is generated at all during
phase 1, it should not be required by downstream tools and should not block the core script-generation flow.

### Question 5

Do you want the dedicated class to remain inside `app/chains/script_chain.py`, or should the refactor create a new
module such as `app/chains/script_generator.py` to keep responsibilities separated from the LCEL adapter?

Answer: Create a new module such as `app/chains/script_generator.py` for the dedicated class, and keep
`app/chains/script_chain.py` as a thin LCEL adapter / entry point. This keeps responsibilities clear: the generator
module owns prompt construction, structured-output invocation, validation, and fallback behavior, while the chain module
stays focused on exposing the Runnable used by `build_pipeline()`.
