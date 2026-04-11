---
description: 'Analyze and brainstorm multiple solutions for the project described in `AGENTS.md`.'
---

# Goal

{{Design the third step of an automated YouTube Shorts pipeline: a Visual Generation (Visual Agent) module using Python and LangChain. The goal is to transform a structured script and optional metadata into a sequence of visual assets (images, short clips, or stock footage) that can be assembled into a coherent short-form video. The output must be consistent, time-aligned with the script, and reusable by downstream components.}}

## Thinking Process

{{We are building the third component of a larger automated video pipeline. The current problem is to design a clean, extensible, and modular Visual Agent system that converts structured script data into visual assets. This module must integrate seamlessly with Script Generation and Voice Generation, and prepare outputs for video assembly, subtitles, and publishing.}}

### 1. Gather and Analyze Project Information

{{Understand that this module consumes structured script output (e.g., hook, body, CTA, optional visual_cues) and possibly audio metadata. It is part of a future multi-agent / pipeline system, so the design must emphasize modularity and clear input/output contracts. The system should support multiple visual sources:
- Stock APIs (e.g., Pexels, Pixabay)
- AI image/video generation (e.g., text-to-image, text-to-video)
- Local asset libraries

The output should be a list of visual segments mapped to script parts, including file paths/URLs, durations, and optional timestamps for alignment with audio.}}

### 2. Algorithm

{{Design a pipeline that takes a structured script (and optional audio metadata) as input and generates visual assets. Steps:
- Input: structured script (JSON) + optional audio duration/timestamps
- Derive visual prompts per segment (hook/body/CTA) using rules or LLM (LangChain Runnable)
- Select visual source strategy (stock vs AI vs hybrid)
- Fetch or generate visuals (images or short clips)
- Normalize assets (resolution, aspect ratio 9:16, format)
- Assign durations and align with script/audio (basic timing or equal splits)
- Validate assets (existence, duration, dimensions)
- Return a reusable visual asset list for downstream video assembly
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

