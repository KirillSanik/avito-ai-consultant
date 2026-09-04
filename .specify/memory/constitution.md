# Project Constitution: Homework AI Reviewer

## Core Principles
- **Architecture:** Strict SOLID and PEP 484 typing (no `Any`). Pass full code to LLM (no truncation). Use local `git` + `pathlib`/`aiofiles` instead of GitHub API.
- **LLM Interaction:** Always use `AsyncOpenAI` with Structured Output (`response_format=PydanticModel`). Never parse raw text with regex. Implement retries (`tenacity`).
- **Testing:** All public methods must be covered by `pytest` + `pytest-asyncio`. Mock all I/O and subprocesses.
- **Code Quality:** Strict DRY. Prefer `ClassVar` over module globals for state. No nested functions.

## Technology Stack
- **Core:** Python 3.10+, dependency management via `uv`.
- **Async & I/O:** `asyncio`, `aiofiles`, `httpx`.
- **API & Validation:** `FastAPI`, `uvicorn`, `pydantic` v2.
- **LLM:** `openai` (AsyncOpenAI).

## Workflow & Governance
- **Pre-commit:** `ruff` linting and `pytest` (≥30% coverage gate) must pass.
- **Reviews:** PRs must strictly comply with this constitution. Deviations require explicit justification.
- **Versioning:** MAJOR (breaking changes), MINOR (new/expanded principles), PATCH (clarifications).

**Version**: 1.2.0 | **Ratified**: 2026-09-03 | **Last Amended**: 2026-09-04