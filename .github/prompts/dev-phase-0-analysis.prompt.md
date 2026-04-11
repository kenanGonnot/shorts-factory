---
description: 'Analyze and brainstorm multiple solutions for the project described in `AGENTS.md`.'
---

# Goal

{{Design the next step of an automated YouTube Shorts pipeline: a Subtitle Generation module using Python and ffmpeg,
integrated as a LangChain-compatible tool. The goal is to transform an assembled vertical video plus existing narration
and timing metadata into a deterministic `.srt` file and a final MP4 with burned-in captions. The output must be
synchronized with the narration timeline, readable on mobile, and directly reusable by the downstream publishing
component.}}

## Thinking Process

{{We are building the next component of a larger automated video pipeline. The current problem is to design a clean,
extensible, and modular Subtitle Generation system that converts the outputs of Video Assembly and Voice Generation into
subtitle artifacts for short-form delivery. This module must integrate cleanly with the assembled `video_path`, the
structured `script`, and available narration timing metadata, while producing stable outputs for publishing in both
normal and degraded modes.}}

### 1. Gather and Analyze Project Information

{{Understand that this module consumes `video_path` produced by `VideoAssemblyTool` and subtitle text/timing context
already present in the pipeline state, primarily `script` and, when available, `audio_segments`, `audio_segments_path`,
and `audio_duration_ms` produced by `VoiceTool`. It is part of a larger LCEL pipeline, so the design must emphasize
modularity, clear input/output contracts, and strict compliance with the `PipelineState` contract from `AGENTS.md`. The
system should account for:

- deterministic caption generation from existing narration chunks instead of depending on external transcription
  services
- silent-audio / offline degraded mode while still producing a valid `.srt` and burned-in final video
- mobile-readable subtitle styling for a 1080x1920 vertical video
- deterministic output storage keyed by `job_id`

The output should be a subtitle file path (`subtitle_path`) and a final burned-in MP4 path (`final_path`) representing
the publishing-ready video generated from the assembled video plus synchronized captions.}}

### 2. Algorithm

{{Design a pipeline that takes the assembled video and subtitle text/timing metadata as input and produces subtitle
artifacts. Steps:

- Input: `video_path` + `script` + optional `audio_segments`, `audio_segments_path`, and `audio_duration_ms`
- Validate that the referenced video exists and that subtitle timing data is available or can be deterministically
  reconstructed from the script
- Convert narration/script content into subtitle cues with start/end timestamps and readable line-breaking/chunking
  rules
- Serialize the subtitle cues into an `.srt` file stored at a deterministic path for the current `job_id`
- Build an ffmpeg burn-in strategy for rendering readable captions onto the vertical video without disturbing the
  existing audio track
- Export the final subtitled MP4 to a deterministic storage path for the current `job_id`
- Validate the resulting `.srt` and MP4 artifacts (exist, playable, duration remains coherent, ready for publishing)
- Return `subtitle_path` and `final_path` for downstream `PublishingTool`
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
