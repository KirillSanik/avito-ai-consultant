# Implementation Plan: Конституционный рефакторинг кодовой базы

**Branch**: `002-constitution-refactor` | **Date**: 2026-09-04 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-constitution-refactor/spec.md`

## Summary

Привести кодовую базу пакета `ai_detector` (src/ + tests/ + конфигурация инструментов)
в полное соответствие Уставу v1.1.0 (`.specify/memory/constitution.md`), не изменяя
наблюдаемого поведения публичного API. Технический подход: инкрементальные
поведенчески-нейтральные срезы (каждый срез — зелёные тесты + зелёный ruff),
механические устранения 11 зафиксированных в базовом аудите отклонений
(B1–B11: дублирование git-ошибкоотчёта, модульные глобалы → ClassVar, вложенные
функции в тестах, `# type: ignore` в LLM-границе, исключение тестов из ruff,
неполное покрытие веток отмены), плюс воспроизводимый артефакт аудита
соответствия (AST-скрипт на stdlib + отчёт).

## Technical Context

**Language/Version**: Python 3.10+ (цель линтера/mypy — py311; рабочее окружение 3.13.3)

**Primary Dependencies**: без новых. Существующие: `pydantic>=2`, `openai>=1.40`, `aiofiles`, `tenacity`, `httpx`; dev: `pytest`, `pytest-asyncio`, `pytest-cov`, `greenlet`. Аудит-скрипт — только stdlib (`ast`, `subprocess`, `pathlib`, `json`).

**Storage**: нет (эфемерные временные клоны git; файловый I/O через `aiofiles`/git CLI)

**Testing**: `pytest` + `pytest-asyncio` (`asyncio_mode="auto"`) + `pytest-cov` (шлюз 30%); статический анализ — `ruff` (набор правил закреплён в `pyproject.toml`)

**Target Platform**: Linux, event loop asyncio, git CLI в PATH

**Project Type**: library (асинхронный Python-модуль)

**Performance Goals**: без изменений к поведению; прогон тест-сьюта ~5 c (база)

**Constraints**: публичный контракт заморожен (фича 001, contracts/public-api.md); тексты ошибок — дословно; каждый срез инкрементален (FR-009); ruff = 0 нарушений в `src/` **и** `tests/` (FR-006); покрытие ≥ 86% (FR-008, SC-004); без живого LLM-сервера (тесты на заглушках)

**Scale/Scope**: пакет ~650 строк (8 модулей), тесты ~1600 строк (9 файлов), 2 demo-скрипта (вне рамок, FR-001 — «0 правок потребителя»); 11 отклонений базового аудита (B1–B11)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Устав v1.1.0: 6 принципов + Technology Stack + Development Workflow + Governance.
Проверка того, что **сам план** не вводит нарушений и прямо закрывает текущие:

| Принцип / раздел | Статус | Комментарий |
|---|---|---|
| I. Architectural Rules (OOP/SOLID, строгая типизация, без Any) | ✅ | План улучшает: B8 (`# type: ignore` → типизированная граница с runtime-проверкой). Новых `Any` не вводится. |
| II. LLM Interaction Rules | ✅ | Контракт Structured Output, tenacity-ретраи, запрет raw-text-парсинга — не затрагиваются; runtime-`isinstance`-проверка объекта, уже распарсенного SDK, парсингом текста не является. |
| III. Testing & Quality | ✅ | B11: добавляются тесты веток отмены `spawn_git`; паттерн моков subprocess/FS сохраняется. |
| IV. DRY | ✅ (цель плана) | B1/B2/B7 устраняются: единый git-ошибкоотчёт, единый shared-модуль тестовых помощников. |
| V. ClassVar Over Module Globals | ✅ (цель плана) | B3: `_REAPERS` → ClassVar на классе-владельце; B4/B5: константы → ClassVar; остаточные модульные константы (если будут) — только immutable класс-независимые, с записью в аудите. |
| VI. No Nested Functions | ✅ (цель плана) | B6: вложенные функции/фейки в тестах → на уровень модуля; исключения (тривиальные замыкания) фиксируются в аудите. |
| Technology Stack | ✅ | Без новых runtime-зависимостей; аудит-скрипт — stdlib. |
| Development Workflow | ✅ (цель плана) | B9/B10: ruff проходит по `src/` и `tests/`; каталог тестов выводится из `exclude`. |
| Governance | ✅ | Устав не поправляется; каждое остающееся отклонение (если останется) обосновывается в аудите (FR-010). |

**GATE RESULT: PASS** — нарушений, требующих обоснования, нет; раздел Complexity Tracking не заполняется.

*Post-design re-check (после Phase 0/1):* решения R1–R10 в [research.md](./research.md)
перепроверены по всем девяти строкам таблицы — расхождений нет; новые отклонения
не введены. **GATE RESULT: PASS (подтверждено).**

## Project Structure

### Documentation (this feature)

```text
specs/002-constitution-refactor/
├── plan.md              # Этот файл (вывод /speckit-plan)
├── research.md          # Вывод Phase 0: решения R1–R10 (Decision/Rationale/Alternatives)
├── data-model.md        # Вывод Phase 1: сущности фичи (замороженный контракт, отчёт аудита)
├── quickstart.md        # Вывод Phase 1: сценарии валидации end-to-end
├── contracts/
│   └── audit-report.md  # Контракт формата артефакта аудита соответствия (FR-010)
└── tasks.md             # Вывод /speckit-tasks (НЕ создаётся этой командой)
```

### Source Code (repository root)

```text
src/ai_detector/
├── __init__.py            # Публичный экспорт — заморожен (FR-001)
├── service.py             # AIDetectionService (фасад) — поведение не меняется
├── repo_cloner.py         # RepoCloner: константы → ClassVar (B4); общие git-хелперы (B1/B2)
├── git_metadata.py        # GitMetadataExtractor: константы → ClassVar (B4); общие git-хелперы
├── code_aggregator.py     # LocalCodeAggregator: константы → ClassVar (B4)
├── llm_judge.py           # LLMJudge: ClassVar (B4/B5); типизированная граница parsed (B8)
├── _spawn.py              # spawn_git: класс-владелец ClassVar-состояния (B3)
└── utils/
    ├── __init__.py
    ├── exceptions.py      # Иерархия исключений — заморожена (FR-001)
    ├── models.py          # CommitInfo/AIAssessmentResult: COMMIT_HASH_PATTERN → ClassVar (B4)
    └── prompts.py         # Промпт-шаблоны — заморожены (контракт 001)

tests/
├── unit/                  # Те же файлы; фейки на уровне модуля (B6), ASYNC110→Event
├── integration/           # Те же файлы; git-хелпер → shared (B7)
└── helpers.py             # НОВЫЙ: общие тестовые помощники (B7: temp-каталоги, git, make_result)

scripts/
└── compliance_audit.py    # НОВЫЙ: воспроизводимый аудит (stdlib-only), FR-010

docs/
└── compliance-audit.md    # НОВЫЙ: сгенерированный отчёт аудита, коммитится в репозиторий

pyproject.toml             # [tool.ruff] exclude: убрать "tests" (B10); прочее — без изменений
demo/                      # Вне рамок (Assumption); должно остаться без правок (SC-005)
```

**Structure Decision**: структура проекта не меняется — рефакторинг
поведенчески-нейтрален. Новые артефакты: `tests/helpers.py` (shared-помощники,
B7), `scripts/compliance_audit.py` + `docs/compliance-audit.md` (FR-010).
Публичный пакет `src/ai_detector/` не получает новых публичных модулей: общие
git-хелперы размещаются в существующем внутреннем `_spawn.py` (решение R1).

## Complexity Tracking

> Раздел не заполняется: Constitution Check пройден без нарушений.
