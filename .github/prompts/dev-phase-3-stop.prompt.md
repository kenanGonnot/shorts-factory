---
description: 'Post prompt'
---
# Post-Prompt Instructions

Read `AGENTS.md`, `implementation-plan.md`, and all related documentation to understand the current state of the project.

## Post-Prompt Actions

- Update `AGENTS.md` and add details that help a developer quickly understand the project.
- If you detect any numbering issues in `AGENTS.md`, correct them.

## Wrap-Up Tasks

- Run all tests and fix any failures.

---

# Prompt – Technical implementation-focused feature reference documents Generator (Optimized)

Your task is to create or update an implementation-focused feature reference document that will be used in future vibe coding sessions. These docs are not product docs. They are LLM maintenance docs: their purpose is to help a future LLM safely understand, modify, and extend a feature without breaking existing behavior, following the template below.

## Goal

Produce or update a Markdown file. The location is:

```
docs/features/{feature_name}.md
```

if it's a UI-related feature. The location is:
```
docs/features/ui/{feature_name}.md
```

## Inputs

Use the content of:

* brainstorming.md
* implementation-plan.md
* project.md

## Output Rules

* Clear, direct English.
* Structured Markdown.
* Include references to the source files.
* If data is missing, write `[MISSING]` and suggest a fix.
* Length: up to 1500 words.
* Output **only** the final Markdown file.

## Required Structure

Keep only the essential sections, in this order:

1. Title — `{feature_name}` + tagline
2. Summary
3. Why (Motivation)
4. Problem Statement
5. In-Scope / Out-of-Scope
6. Acceptance Criteria (Given/When/Then)
7. API & Interfaces
8. Detailed Design (How)
      - Must include at least one **Mermaid diagram** (flowchart, sequence diagram, or architecture diagram).
9. Testing

### Extras

* Add an acceptance test summary table.
* Include code blocks where relevant.

## Start the file with

```
# {feature_name} — {tagline}
```
