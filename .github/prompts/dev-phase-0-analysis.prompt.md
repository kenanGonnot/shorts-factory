---
description: 'Analyze and brainstorm multiple solutions for the project described in `AGENTS.md`.'
---

# Goal

{{Design the next step of an automated YouTube Shorts pipeline: a Publishing module using Python and the YouTube Data
API, integrated as a LangChain-compatible tool. The goal is to transform the final subtitled vertical video plus
structured script metadata into a publish-ready upload flow that either returns a real YouTube video identifier or a
deterministic dry-run result when credentials are missing. The output must preserve clean pipeline contracts, support
degraded mode without secrets, and be directly reusable by the job tracking and API layers.}}

## Thinking Process

{{We are building the next component of a larger automated video pipeline. The current problem is to design a clean,
extensible, and modular Subtitle Generation system that converts the outputs of Video Assembly and Voice Generation into
subtitle artifacts for short-form delivery. This module must integrate cleanly with the assembled `video_path`, the
structured `script`, and available narration timing metadata, while producing stable outputs for publishing in both
normal and degraded modes.}}

### 1. Gather and Analyze Project Information

{{Understand that this module consumes `final_path` produced by `SubtitleTool` and the structured `script` metadata
already present in the pipeline state, especially `title`, `hook`, `body`, `cta`, and `tags`. It is part of a larger
LCEL pipeline, so the design must emphasize modularity, clear input/output contracts, and strict compliance with the
`PipelineState` contract from `AGENTS.md`. The system should account for:

- upload of the final 9:16 MP4 through a clean service wrapper instead of embedding YouTube API details directly in the
  tool
- deterministic degraded mode when `YOUTUBE_CLIENT_SECRETS_FILE` or related credentials are missing
- metadata construction from the generated script, including title, description, tags, and privacy settings
- idempotent or at least stable behavior keyed by `job_id` when possible, so repeated runs remain predictable

The output should be a YouTube identifier field (`youtube_id`) representing either the real uploaded video id or a
stable dry-run value when publication is skipped.}}

### 2. Algorithm

{{Design a pipeline that takes the finalized short and script metadata as input and produces a publication result.
Steps:

- Input: `final_path` + `script`
- Validate that the referenced final video exists and that the minimum publication metadata can be derived from the
  script
- Build upload metadata deterministically from the script, including a Shorts-friendly title, description, tags, and
  configured privacy status
- Resolve publishing mode from configuration: real YouTube upload when OAuth credentials are available, or degraded
  dry-run otherwise
- In real upload mode, initialize the YouTube client lazily, submit the MP4 upload, and capture the returned remote
  video identifier
- In dry-run mode, emit a stable placeholder identifier and structured logs that clearly explain why publication was
  skipped
- Validate the publication result so downstream API, worker, and persistence layers can rely on a single `youtube_id`
  contract
- Return `youtube_id` for the completed pipeline state
  }}

#### Behavioral Rules

{{

- Use clean modular architecture
- Prefer composition over complex inheritance
- Use LangChain Runnable / LCEL for prompt generation
- Abstract providers (stock/AI) behind a clean interface
- Keep logic simple (KISS)
- Ensure each component is testable
- Optimize for future pipeline integration and scalability
  }}

### Notes

{{

- This is the third stage of a larger YouTube Shorts automation pipeline
- Inputs come from Script (and optionally Voice) modules
- Output must be directly usable by Video Assembly (ffmpeg)
- Prefer deterministic behavior with optional LLM assistance for prompts
- Avoid over-engineering but define a stable contract
  }}

### 3. Architecture

Design the change so it is encapsulated within a dedicated class.

## Implementation Notes

* Python 3.11+ only. Use modern features (e.g., type hints, structural pattern matching). Avoid outdated patterns like
  hasattr or getattr.
* Use KISS principles to keep the code simple and maintainable.

### Steps :

1. Read the file named `AGENTS.md` to get more insights on the project.
2. Research online using `google-search` or `brave-search` to get ideas.
3. Write 3 potential solutions in `brainstorming.md`. Add a basic example to demonstrate each solution.
4. Select comparison criteria for the solutions, such as pros and cons, complexity of implementation, key differences,
   usage complexity, etc.
5. Create a summary table in `brainstorming.md` with these criteria to compare the solutions.
6. From these, choose the best solution to implement and update brainstorming.md accordingly.

### Deliverable:

The `brainstorming.md` should contain these sections:

1. Description of the problem.
2. Research summary
3. Thinking process
4. Solutions
    * For each solution, create a subsection with:
        * Description
        * Example
5. Comparison criteria & Summary Table
    * Comparison criteria
    * Summary Table
    * Ranked solutions
6. Choosen solution
7. Notes
8. Ask clarification on unclear topic.
    * Ask questions
    * Write "Answer: " under the question and leave it blank for the user to fill in later.
    * "GPT recommendation: " under the answer section to give your recommendation on the best solution to implement
      based on the analysis.

### Constraints:

* Only modify `brainstorming.md` for now.
* Generate a human readable markdown file. Create clear sections with titles and subtitles.
* Do not consider backward compatibility strategy; ensure the code is fully up to date.
* Do not implement the solution yet, just do the analysis.
