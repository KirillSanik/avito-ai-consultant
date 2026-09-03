# Implementation Plan: Homework AI Detector

**Branch**: `001-homework-ai-detector` | **Date**: 2026-09-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-homework-ai-detector/spec.md`

## Summary

Модуль принимает на вход текст критериев домашнего задания и URL репозитория с решением: локально скачивает полную копию репозитория через `git`, **параллельно** извлекает полную историю коммитов и весь исходный код (без усечения), передаёт их в локальную LLM через OpenAI-совместимый API со Structured Output и возвращает валидированный pydantic-объект `AIAssessmentResult` — вердикт «Светофор» (green/yellow/red) с уверенностью, обоснованием на русском и списками признаков AI-/человеческой генерации.

Технический подход (из research.md): трёхслойная архитектура — Data Layer (`RepoCloner` асинхронный контекстный менеджер, `GitMetadataExtractor`, `LocalCodeAggregator`), Evaluation Layer (`LLMJudge`), Orchestration Layer (фасад `AIDetectionService`, `asyncio.gather` для параллельного сбора). Стек строго зафиксирован конституцией: Python 3.10+, `uv`, `asyncio`/`aiofiles`/`httpx`, `pydantic` v2, `AsyncOpenAI` + `tenacity`.

## Technical Context

**Language/Version**: Python 3.10+ (совместимо с 3.11/3.12)

**Primary Dependencies**: `pydantic` v2, `openai` (AsyncOpenAI, OpenAI-совместимый), `aiofiles`, `tenacity`, `httpx` (транзитивно через `openai`); системная зависимость — CLI-клиент `git`

**Storage**: N/A — модуль без состояния; результаты возвращаются вызывающей в памяти. Единственное хранение — эфемерный каталог с клонированным репозиторием, гарантированно удаляемый после анализа (в т.ч. при ошибках).

**Testing**: `pytest` + `pytest-asyncio`; моки для `asyncio.create_subprocess_exec`, файлового I/O и `AsyncOpenAI`

**Target Platform**: Linux/macOS сервер с установленным `git` CLI; сеть для клонирования; локальный LLM-сервер (vLLM/Triton) с OpenAI-совместимым API

**Project Type**: Python-библиотека (импортируемый модуль) с программным API; без CLI/веб-слоя в v1

**Performance Goals**: полный анализ типового студенческого репозитория (до 20 поддерживаемых файлов) < 5 минут end-to-end (SC-001); сбор метаданных + кода выполняется параллельно и занимает малую долю общего времени (FR-006, SC-001)

**Constraints**: полное содержимое файлов без усечения (FR-004, конституция §2); запрет GitHub API — только `git` CLI (FR-002, конституция §2); строгая типизация, `Any` запрещён, если не обосновано; гарантированная очистка временных данных при любом исходе (FR-010); только явные ошибки вместо частичных/невалидных результатов (FR-013)

**Scale/Scope**: один репозиторий за вызов (batch — вне scope v1); типовой репозиторий — до ~20 поддерживаемых файлов; суммарный объём кода передаётся в модель целиком; число повторов при сбое LLM — 3

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Конституция: [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md)

| # | Статья конституции | Gate для данного плана | Status |
|---|--------------------|------------------------|--------|
| 1 | Core Tech Stack (Python 3.10+, `uv`, `asyncio`/`aiofiles`/`httpx`, `pydantic` v2, `AsyncOpenAI`) | Technical Context точно соответствует стеку; зависимости управляются через `uv` (pyproject.toml + uv.lock) | ✅ PASS |
| 2 | Architectural Rules (SOLID, строгие type hints, без `Any`, без усечения кода, без GitHub API) | 5 классов с единой ответственностью (SOLID); полная типизация PEP 484; полный код в промпт; только `git clone`/`git log`/`git ls-files` + `pathlib`/`aiofiles` | ✅ PASS |
| 3 | LLM Interaction Rules (`response_format=PydanticModel`, без regex-парсинга LLM-текста, `tenacity` на все LLM-вызовы) | `LLMJudge` использует `AsyncOpenAI.beta.chat.completions.parse(response_format=AIAssessmentResult)`; возврат только `.parsed`/`model_validate`; retry через `tenacity` (3 попытки) | ✅ PASS |
| 4 | Testing & Quality (`pytest` + `pytest-asyncio` на все public-методы, моки subprocess и fs I/O) | Тестовый план покрывает все public-методы; `create_subprocess_exec`, файловый I/O и `AsyncOpenAI` мокируются (см. quickstart.md) | ✅ PASS |

**Gate result: PASS** — нарушений нет, раздел Complexity Tracking не требуется.

**Повторная проверка после Phase 1 design**: ✅ PASS — data-model.md, contracts/ и quickstart.md не вводят новых технологий/зависимостей; схема Structured Output, параллельный сбор и гарантированная очистка согласованы со статьями §1–§4.

## Project Structure

### Documentation (this feature)

```text
specs/001-homework-ai-detector/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── public-api.md
│   └── llm-structured-output.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/
└── ai_detector/
    ├── __init__.py          # публичный экспорт: AIDetectionService, AIAssessmentResult, CommitInfo, исключения
    ├── models.py            # pydantic v2: AIAssessmentResult, CommitInfo
    ├── exceptions.py        # иерархия доменных исключений (RepoCloneError, MetadataExtractionError, CodeAggregationError, LLMJudgementError)
    ├── prompts.py           # шаблоны system/user промптов (критерии «Светофора»)
    ├── repo_cloner.py       # RepoCloner — асинхронный контекстный менеджер, git clone, очистка
    ├── git_metadata.py      # GitMetadataExtractor — git log (JSON) + git ls-files
    ├── code_aggregator.py   # LocalCodeAggregator — rglob, whitelist/blacklist, aiofiles, Semaphore
    ├── llm_judge.py         # LLMJudge — AsyncOpenAI beta .parse(), tenacity retry
    └── service.py           # AIDetectionService — фасад, asyncio.gather

tests/
├── unit/
│   ├── test_repo_cloner.py
│   ├── test_git_metadata.py
│   ├── test_code_aggregator.py
│   ├── test_llm_judge.py
│   └── test_service.py
└── integration/
    └── test_pipeline_smoke.py   # пайплайн на фикстуре репозитория + мок LLM

pyproject.toml               # uv: зависимости, [tool.pytest.ini_options]
uv.lock
```

**Structure Decision**: выбран Option 1 (single project, src-layout) — проект является одной Python-библиотекой без фронтенда и без отдельного API-сервера, поэтому варианты 2 и 3 исключены. Папка `src/ai_detector` соответствует src-layout, рекомендованному `uv` для пакетов; тесты разделены на unit (моки subprocess/fs/LLM) и integration (сборный сценарий пайплайна).
