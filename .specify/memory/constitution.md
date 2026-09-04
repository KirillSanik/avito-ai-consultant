<!--
SYNC IMPACT REPORT
=================
Version change: unversioned baseline (treated as 1.0.0) -> 1.1.0
Bump type: MINOR (three new principles added; no removals or redefinitions)
Modified principles (relocated into template structure, content preserved):
  - "1. Core Tech Stack" -> section "Technology Stack" (content unchanged)
  - "2. Architectural Rules" -> Principle "I. Architectural Rules"
  - "3. LLM Interaction Rules" -> Principle "II. LLM Interaction Rules"
  - "4. Testing & Quality" -> Principle "III. Testing & Quality"
Added sections:
  - Principle "IV. DRY (Don't Repeat Yourself)"
  - Principle "V. ClassVar Over Module Globals"
  - Principle "VI. No Nested Functions"
  - Section "Development Workflow" (derived from pyproject.toml gates)
  - Section "Governance" + version footer
Removed sections: none (all prior content preserved)
Deferred TODOs: none
-->

# Project Constitution: Homework AI Detector

## Core Principles

### I. Architectural Rules
- Strict Object-Oriented Design with SOLID principles.
- Strict type hints (PEP 484) everywhere. No `Any` unless absolutely necessary.
- No token economy: pass FULL code files to LLM, do not truncate.
- No GitHub API for repo data: use local `git clone` + `git log` + `pathlib`/`aiofiles`.

### II. LLM Interaction Rules
- Always use `AsyncOpenAI` with `response_format=PydanticModel` (Structured Output).
- Never parse raw LLM text with regex; rely on `.parse()` or `.model_validate_json()`.
- Implement retry logic (`tenacity`) for all LLM calls.

### III. Testing & Quality
- All public methods must be covered by `pytest` + `pytest-asyncio`.
- Mock subprocess and filesystem I/O in tests.

### IV. DRY (Don't Repeat Yourself)
- Every piece of knowledge or logic MUST have a single, unambiguous, authoritative
  representation within the codebase.
- A rule, algorithm, or value that appears in more than one place MUST be extracted
  into a shared function, class, or named constant.
- Rationale: duplicated logic diverges over time; a single change point keeps behavior
  consistent and makes review and refactoring cheaper.

### V. ClassVar Over Module Globals
- Shared configuration and state MUST be declared as class-level attributes
  (`typing.ClassVar`) on the owning class instead of module-level global variables,
  wherever possible.
- Module-level globals are permitted only for immutable, class-agnostic constants
  (regex patterns, protocol/format strings) with no natural owning class.
- Rationale: class-scoped state is typed, discoverable, and bound to the lifecycle of
  its owner; module globals create hidden coupling between unrelated modules.

### VI. No Nested Functions
- Functions MUST NOT be declared inside other functions wherever possible; extract them
  to module level with explicit arguments or make them methods of a class.
- Permitted exception: a trivial one-off closure whose only purpose is to pass a value
  into a higher-order function (e.g., a callback), where extraction would add naming
  noise without any reuse.
- Rationale: nested functions hide the API surface, cannot be imported or tested
  directly, and implicitly capture local (often mutable) state.

## Technology Stack
- Python 3.10+
- Dependency management: `uv` (pyproject.toml, uv.lock)
- Async I/O: `asyncio`, `aiofiles`, `httpx`
- Validation: `pydantic` v2.x
- LLM Client: `openai` (AsyncOpenAI, compatible with local vLLM/Triton)

## Development Workflow
- Static analysis: `ruff` (rule selection pinned in `pyproject.toml`) MUST pass on
  `src/` and `tests/` before commit.
- Tests: `uv run pytest` (unit + integration) MUST be green; coverage gate is
  `--cov-fail-under=30` (`pyproject.toml`).
- Code review MUST verify compliance with the Core Principles; complexity that goes
  beyond these rules requires an explicit justification in the commit/PR description.

## Governance
- This constitution supersedes all other development practices in the repository.
- Amendment procedure: (1) update this file, (2) increment the version per the policy
  below, (3) refresh the Sync Impact Report at the top of this file.
- Versioning policy: MAJOR — backward-incompatible principle removal or redefinition;
  MINOR — new principle/section added or materially expanded guidance;
  PATCH — clarifications, wording, typo fixes, non-semantic refinements.
- Compliance review: all PRs/reviews MUST verify compliance with the Core Principles;
  any deviation requires an explicit, documented justification.

**Version**: 1.1.0 | **Ratified**: 2026-09-03 | **Last Amended**: 2026-09-04
