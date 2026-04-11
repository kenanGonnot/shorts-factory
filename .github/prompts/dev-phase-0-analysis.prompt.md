---
description: 'Analyze and brainstorm multiple solutions for the project described in `AGENTS.md`.'
---

# Goal

{{Design the fourth step of an automated YouTube Shorts pipeline: a Video Assembly module using Python and ffmpeg, integrated as a LangChain-compatible tool. The goal is to transform normalized visual assets and a narration audio track into a single vertical short-form video file. The output must be deterministic, synchronized with the audio timeline, and directly reusable by downstream subtitle and publishing components.}}

## Thinking Process

{{We are building the fourth component of a larger automated video pipeline. The current problem is to design a clean, extensible, and modular Video Assembly system that combines the outputs of Voice Generation and Visual Generation into a single video artifact. This module must integrate seamlessly with upstream normalized visual assets and narration audio, and prepare a stable output for subtitles and publishing.}}

### 1. Gather and Analyze Project Information

{{Understand that this module consumes `visual_assets` produced by `VisualTool` and `audio_path` produced by `VoiceTool`, with optional timing metadata such as `audio_duration_ms`. It is part of a larger LCEL pipeline, so the design must emphasize modularity, clear input/output contracts, and strict compliance with the `PipelineState` contract from `AGENTS.md`. The system should account for:
- pre-normalized vertical MP4 clips coming from the visual stage
- fallback/offline visual assets and silent audio in degraded mode
- deterministic output storage keyed by `job_id`

The output should be a single assembled video file path (`video_path`) representing the subtitle-ready MP4 generated from sequenced visuals plus muxed narration audio.}}

### 2. Algorithm

{{Design a pipeline that takes normalized visual assets and narration audio as input and produces a single assembled video. Steps:
- Input: `visual_assets` manifest + `audio_path` + optional duration metadata
- Validate that the referenced assets exist and are usable for assembly
- Determine sequencing and effective clip durations so the visual timeline matches the narration length
- Build an ffmpeg assembly strategy (concat/filtergraph) for stitching the clips into one continuous 1080x1920 video
- Mux the final narration audio onto the assembled visual timeline
- Export the result to a deterministic storage path for the current `job_id`
- Validate the resulting MP4 (exists, playable, expected duration, ready for subtitles)
- Return `video_path` for downstream `SubtitleTool`
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
    * "GPT recommendation: " under the answer section to give your recommendation on the best solution to implement based on the analysis.

### Constraints:

* Only modify `brainstorming.md` for now.
* Generate a human readable markdown file. Create clear sections with titles and subtitles.
* Do not consider backward compatibility strategy; ensure the code is fully up to date.
* Do not implement the solution yet, just do the analysis.
