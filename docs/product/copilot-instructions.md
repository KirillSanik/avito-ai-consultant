# Repository Instructions & System Context

## System Overview
AI Reviewer: Automated 3-stage homework review pipeline (Task Ingestion -> Submission Parsing -> Criterion-by-Criterion Evaluation).

## Key Product Documentation
Refer to the following files in `docs/product/` for domain requirements and architectural constraints:
- PROJECT_DESCRIPTION_INTERIM.md (Full architecture, PoC specs, pipeline layout)
- PRODUCT_01_USER_PROBLEM_VALUE.md (User roles, problems, value proposition)
- PRODUCT_02_MVP_SCENARIO_DECISIONS.md (MVP boundaries, human-in-the-loop decisions)
- PRODUCT_03_VALIDATION_RISKS_PILOT.md (Success metrics and risk mitigation)

## Technical Architecture & LLM Policy
- Tech Stack: Python 3.11+, Pydantic v2, Instructor, Click, git CLI.
- LLM Provider Strategy: Primary execution MUST use external Cloud APIs (OpenRouter or Gemini) via `common/llm/` (client factory + instructor) instead of local Ollama/Qwen.
- Storage Location: All JSON state outputs persist under `storage/tasks/`, `storage/submissions/`, and `storage/evaluations/` (local, git-ignored).

## Strict Formatting Rules
- Do not write inline comments inside Python code blocks.
- Use Pydantic v2 schemas for all payload validations.
- Catch network and DNS resolution errors gracefully without crashing execution.

