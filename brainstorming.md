# Brainstorming — Script Generation Module for Shorts Factory

## 1. Description of the problem

Shorts Factory needs a first-class **Script Generation** module that turns a user-provided `topic` into a **structured
short-form video script** that can be consumed by the rest of the pipeline.
This is the entry point of the current LCEL pipeline:

```text
topic → ScriptChain → VoiceTool → VisualTool → VideoAssemblyTool → SubtitleTool → PublishingTool
```

The module must produce a stable object that matches the current project contract in `app/chains/state.py`:

- `title: str`
- `hook: str`
- `body: str`
- `cta: str`
- `tags: list[str]`
  The design must stay aligned with the repository conventions from `AGENTS.md`:
- use **LangChain Runnable / LCEL**
- keep the component **modular and testable**
- prefer **simple composition**
- return **structured data**, not raw prose
- preserve the future pipeline contract for TTS, visuals, subtitles, and publishing
- support a **degraded mode** when API keys are missing
  The main design challenge is to choose the right balance between:

1. **speed of implementation**
2. **schema reliability**
3. **testability**
4. **future extensibility**
5. **compatibility with downstream automation**

---

## 2. Research summary

### Repository findings

From the current repository:

- `README.md` defines script generation as the first pipeline step and expects a structured script with `title`, `hook`,
  `body`, `cta`, and `tags`.
- `app/chains/script_chain.py` currently uses:
    - `ChatPromptTemplate`
    - `ChatOpenAI`
    - `JsonOutputParser`
    - `RunnableLambda`
- `app/chains/state.py` defines a lightweight `Script` `TypedDict` and stores the result in `PipelineState["script"]`.
- `tests/test_pipeline.py` confirms the current downstream expectation: the script is treated as one structured object
  and `body` is currently a single `str`, not a list of lines.
- `AGENTS.md` adds an important constraint not yet fully reflected in the current script chain: **the pipeline should
  still run in degraded mode even without API keys**.

### Online research summary

Brief online research highlights the following useful guidance:

1. **LangChain structured output docs** recommend schema-driven structured responses instead of relying only on raw JSON
   text parsing. The modern pattern is to use `with_structured_output(...)` with a Pydantic model or JSON schema, which
   improves response reliability and validation.
2. Current short-form video guidance consistently emphasizes:
    - a **strong hook in the first 2–3 seconds**
    - **one core idea per short**
    - **tight pacing**
    - a clear **payoff / CTA**
    - scripts kept concise enough for roughly **15–35 seconds** or around the repo target of **~30 seconds**
3. For downstream automation, the most important property is not “creative prose quality” alone, but **predictable
   structure** and **validated content**.

### Key implication

The best design should not stop at “parse some JSON”. It should also:

- validate required fields
- validate content shape and basic limits
- make failure modes explicit
- provide a deterministic fallback when the LLM cannot be used

---

## 3. Thinking process

This module is foundational because it defines the contract for all later stages.
A good solution should answer these practical questions:

- How do we guarantee that the script object is always complete?
- How do we keep the API simple for the rest of the pipeline?
- How do we remain compatible with LCEL and the existing `build_pipeline()` composition?
- How do we avoid over-engineering at phase 0?
- How do we support development without requiring a live LLM key?
  The current implementation is already close to the target architecture, but it is still minimal:
- it parses JSON
- it does not strongly validate the returned structure
- it is not encapsulated in a dedicated class
- it does not clearly solve degraded-mode generation
  So the analysis focuses on three viable directions:

1. keep the current shape and improve it incrementally
2. introduce a dedicated class with schema-driven structured output
3. introduce a multi-pass generation-and-repair design for maximum robustness
   The best option should improve correctness without making the first module unnecessarily complex.

---

## 4. Solutions

### Solution 1 — Minimal LCEL chain with JSON parsing + manual validation

#### Description

Keep the current architecture very close to what already exists:

- prompt template
- `ChatOpenAI`
- `JsonOutputParser`
- small validation function after parsing
- `RunnableLambda` adapter to map `PipelineState -> PipelineState`
  This approach preserves the existing mental model and requires the fewest code changes. A post-parse validator would
  check:
- required keys exist
- strings are non-empty
- `tags` is a list of lowercase strings
- title length is acceptable
- body length stays roughly in target range
  A fallback function could generate a deterministic template script when no API key is configured.

#### Example

```python
prompt | llm | JsonOutputParser() | validate_script_dict
```

Example output:

```json
{
  "title": "3 octopus facts that feel fake",
  "hook": "Octopuses have three hearts — and that's just the start.",
  "body": "They can solve puzzles fast. Their blood is blue. And they can squeeze through tiny gaps because they have no bones.",
  "cta": "Follow for more weird science facts.",
  "tags": [
    "science",
    "animals",
    "octopus",
    "facts",
    "shorts"
  ]
}
```

#### Why it is attractive

- fastest to implement
- minimal refactor
- keeps current LCEL style
- easy to understand

#### Main limitation

Validation happens **after** generation, so the LLM is still free to produce malformed output first.
---

### Solution 2 — Dedicated `ScriptGenerator` class with schema-driven structured output

#### Description

Create a dedicated class responsible for:

- prompt construction
- structured-output LLM invocation
- schema validation
- fallback generation
- conversion to the exact `PipelineState` contract
  The class would encapsulate the script-generation behavior while still exposing a Runnable-compatible entry point for
  `build_pipeline()`.
  Core idea:
- define a Pydantic model or explicit JSON schema for the script
- ask the LLM for structured output using LangChain’s schema-aware APIs
- validate content constraints in one place
- return a plain dict matching the existing `Script` shape
- if no key is available, build a deterministic fallback script from the topic
  This matches the prompt instruction to **encapsulate the change within a dedicated class** while keeping LCEL
  compatibility.

#### Example

```python
class ScriptGenerator:
    def build_runnable(self) -> Runnable:
        ...
```

Potential internal flow:

```python
prompt -> structured_llm -> validated_script_model -> state_adapter
```

Example output:

```json
{
  "title": "Why coffee sharpens your focus",
  "hook": "Coffee doesn't give you energy the way you think.",
  "body": "Caffeine blocks the signals that make you feel tired. That means your brain feels more alert fast. But timing matters, or you'll crash later.",
  "cta": "Subscribe for more fast science explainers.",
  "tags": [
    "coffee",
    "focus",
    "science",
    "brain",
    "shorts"
  ]
}
```

#### Why it is attractive

- strongest balance of structure and simplicity
- clearer separation of responsibilities
- easy to test in isolation
- natural place for fallback behavior
- future-proof for richer validation or additional fields

#### Main limitation

Slightly more implementation effort than Solution 1.
---

### Solution 3 — Two-pass generation with validation and repair

#### Description

Use a two-step flow:

1. generate a candidate script
2. run a second validation/repair pass if the candidate is incomplete, too long, or poorly formatted
   This can be implemented as:

- prompt A: generate draft script
- parser/schema validation
- if invalid, prompt B: repair to fit schema and constraints
  This solution is the most robust against model drift, but it introduces extra complexity, extra latency, and more
  moving parts at the very first stage of the project.

#### Example

```python
draft = draft_chain.invoke({"topic": topic})
script = repair_chain.invoke({"draft": draft, "errors": validation_errors})
```

Example behavior:

- first pass returns 10 tags and a 130-word body
- validator flags violations
- repair pass rewrites to 5 tags and a short body

#### Why it is attractive

- best resilience against malformed outputs
- explicit handling of bad model responses
- can improve consistency for production later

#### Main limitation

It is likely too heavy for phase 0 and conflicts with the project’s KISS guidance unless reliability problems are already observed in practice.
---

## 5. Comparison criteria & Summary Table

### Comparison criteria

The solutions were compared using these criteria:

1. **Implementation complexity**
2. **Reliability of structured output**
3. **Fit with current LCEL architecture**
4. **Ease of isolated testing**
5. **Support for degraded mode**
6. **Clarity of ownership / encapsulation**
7. **Readiness for downstream pipeline stages**
8. **Risk of over-engineering at this stage**

### Summary Table

| Solution                                  | Reliability | Complexity | LCEL fit  | Testability | Degraded mode fit | Future extensibility | Main trade-off                                              |
|-------------------------------------------|-------------|-----------:|-----------|-------------|-------------------|----------------------|-------------------------------------------------------------|
| 1. JSON parser + manual validation        | Medium      |        Low | Excellent | Good        | Good              | Medium               | Simple, but validation is reactive rather than schema-first |
| 2. Dedicated class + schema-driven output | High        |     Medium | Excellent | Excellent   | Excellent         | High                 | Slightly more setup, but best long-term contract            |
| 3. Two-pass generation + repair           | Very high   |       High | Good      | Medium      | Good              | Very high            | Most robust, but too complex for phase 0                    |

### Ranked solutions

1. **Solution 2 — Dedicated class + schema-driven output**
2. **Solution 1 — JSON parser + manual validation**
3. **Solution 3 — Two-pass generation + repair**

---

## 6. Choosen solution

### Selected option

**Solution 2 — Dedicated `ScriptGenerator` class with schema-driven structured output**

### Why this is the best choice

This option best matches both the repository and the phase-0 objective:

- It stays **simple enough** for the first implementation.
- It respects the instruction to use a **dedicated class**.
- It still fits naturally into **LCEL** by exposing a Runnable-compatible interface.
- It offers a **stronger schema contract** than plain JSON parsing.
- It gives one clean place to implement **fallback logic**, validation, and future enhancements.
- It protects downstream tools by making the script object more trustworthy.

### Recommended design direction

The implementation should likely look like this conceptually:

1. Define a schema model for the script output.
2. Build a specialized short-form prompt around:
    - one strong hook
    - short body
    - clear CTA
    - five tags
3. Invoke the LLM using structured-output support when available.
4. Validate business constraints in one dedicated place.
5. Convert the result into the project’s current `Script` dict shape.
6. If no OpenAI key is available, generate a deterministic fallback script so the pipeline still runs end-to-end.
7. Wrap the class in a Runnable entry point that enriches `PipelineState` with `script`.

### Why not the other options

- **Solution 1** is acceptable, but it keeps too much responsibility spread across prompt text, parser behavior, and ad
  hoc validation.
- **Solution 3** is attractive for a later production-hardening phase, but it adds too much orchestration for the first
  module.

---

## 7. Notes

- `project.md` is not present in this workspace, so this analysis used `AGENTS.md`, `README.md`,
  `app/chains/script_chain.py`, `app/chains/state.py`, `app/chains/pipeline.py`, and `tests/test_pipeline.py` as the
  project brief.
- The active repository is **Shorts Factory**. The externally referenced prompt path appears to belong to a different
  project; its process format was useful, but its feature domain does not match this workspace.
- The current `Script` contract uses `body: str`. If subtitle timing or shot planning becomes important soon, a future
  revision may benefit from a richer representation such as `body_lines: list[str]` or a scene list, but that is not
  required for phase 0.
- A degraded-mode script fallback is important because `AGENTS.md` states that the pipeline should run without external
  API keys.
- The module should remain **focused on script generation only** for now. Timing, narration cues, shot breakdowns, and
  publishing metadata can be layered later without blocking this first step.

---

## 8. Ask clarification on unclear topic

### Question 1

Should the generated script always be in the same language as the input topic, or should the pipeline enforce a default
language such as French or English?
Answer: Enforce a default language (English) for now, but allow the prompt to specify that the script should be in the
same language as the topic if it is not English.

### Question 2

Should the `body` remain a single string for now, or do you want the script module to prepare a more structured format
such as lines or scenes for subtitles and editing later?
Answer:Script module should prepare a more structured format such as lines for subtitles and editing later.

### Question 3

Do you want the script generator to include only content text, or should it also prepare optional metadata such as
estimated duration, pacing notes, or visual cues?
Answer: It should also prepare optional metadata such as estimated duration, pacing notes, or visual cues, but these can
be optional fields in the output schema that downstream modules can choose to use or ignore based on their needs.

### Question 4

When no LLM API key is configured, should the fallback script be a deterministic template based on the topic, or should
the module fail fast instead?
Answer:Should the module faile fast instead

### Question 5

The referenced prompt path points to another repository. Should the local `shorts-factory` analysis prompt be treated as
the source of truth for future phases?
Answer: Yes, the local `shorts-factory` analysis prompt should be treated as the source of truth for future phases. 
