# Project Constitution: Homework AI Detector

## 1. Core Tech Stack
- Python 3.10+
- Dependency management: `uv` (pyproject.toml, uv.lock)
- Async I/O: `asyncio`, `aiofiles`, `httpx`
- Validation: `pydantic` v2.x
- LLM Client: `openai` (AsyncOpenAI, compatible with local vLLM/Triton)

## 2. Architectural Rules
- Strict Object-Oriented Design with SOLID principles.
- Strict type hints (PEP 484) everywhere. No `Any` unless absolutely necessary.
- No token economy: pass FULL code files to LLM, do not truncate.
- No GitHub API for repo data: use local `git clone` + `git log` + `pathlib`/`aiofiles`.

## 3. LLM Interaction Rules
- Always use `AsyncOpenAI` with `response_format=PydanticModel` (Structured Output).
- Never parse raw LLM text with regex; rely on `.parse()` or `.model_validate_json()`.
- Implement retry logic (`tenacity`) for all LLM calls.

## 4. Testing & Quality
- All public methods must be covered by `pytest` + `pytest-asyncio`.
- Mock subprocess and filesystem I/O in tests.