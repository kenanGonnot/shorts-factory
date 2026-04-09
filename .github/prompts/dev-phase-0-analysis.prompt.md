---
description: 'Analyze and brainstorm multiple solutions for the project described in `project.md`.'
---

# Goal

{{Design the first step of an automated YouTube Shorts pipeline: a Script Generation module using Python and LangChain.
The goal is to transform a given topic into a structured, reusable short-form video script optimized for downstream
automation. The generated output must be concise, validated, and formatted so it can later be consumed by future
pipeline stages such as TTS, video assembly, subtitles, and publishing.}}

## Thinking Process

{{We are building the first foundational component of a larger automated YouTube Shorts pipeline. At this stage, the
focus is only on script generation. The problem is to design a clean, extensible, and modular system that takes a topic
as input and produces a structured script output ready for later stages. This first module should be simple enough to
implement quickly, but robust enough to serve as a reliable interface for the rest of the pipeline.}}

### 1. Gather and Analyze Project Information

{{Understand that this module is the entry point of a future multi-step automation system. Its responsibility is to
generate a short-form script in a predictable structure, not just raw text. The design should emphasize clarity,
modularity, and compatibility with downstream components. Since this is the first stage, the structure of the script
output is especially important because it will define the contract for future modules.}}

### 2. Algorithm

{{Design a pipeline that takes a topic as input and generates a structured YouTube Shorts script. Steps:

- Input: topic
- Build a prompt template specialized for short-form video generation
- Invoke the LLM through LangChain
- Parse the response into a structured JSON format
- Validate the schema and content fields
- Return a reusable script object for downstream pipeline stages
  }}

#### Behavioral Rules

{{

- Use clean modular architecture
- Prefer composition over complex inheritance
- Use LangChain Runnable / LCEL
- Enforce structured outputs (no raw text)
- Keep logic simple (KISS)
- Ensure each component is testable
- Optimize for future pipeline integration
  }}

### Notes

{{

- This is the first stage of a larger YouTube Shorts automation pipeline
- The scope is limited to script generation only
- The output structure should be stable and reusable by downstream modules
- Avoid over-engineering, but define a clean contract for future steps
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

### Constraints:

* Only modify `brainstorming.md` for now.
* Generate a human readable markdown file. Create clear sections with titles and subtitles.
* Do not consider backward compatibility strategy; ensure the code is fully up to date.
* Do not implement the solution yet, just do the analysis.

