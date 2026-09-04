---

description: "Task list for feature 002-constitution-refactor"
---

# Tasks: Конституционный рефакторинг кодовой базы

**Input**: Design documents from `/specs/002-constitution-refactor/`

**Prerequisites**: plan.md, spec.md, research.md (R1–R10), data-model.md, contracts/audit-report.md, quickstart.md

**Tests**: включены — фича явно требует тестовой работы (FR-007: приведение кода тестов к принципам; FR-008: покрытие публичных методов, включая ветки отмены `spawn_git`; R8: новый файл `tests/unit/test_spawn.py`). Задачи T022 фиксируют **существующее** поведение (regression-pinning): они зелёны с первого запуска и защищают рефакторинг.

**Organization**: задачи сгруппированы по user story (spec.md) для независимой реализации и проверки каждой.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: может выполняться параллельно (другие файлы, нет зависимостей на незавершённые задачи)
- **[Story]**: к какому user story относится задача (US1–US4)
- В описании — точные пути файлов

## Path Conventions

- Single project: `src/`, `tests/` в корне репозитория; новые артефакты — `scripts/`, `docs/compliance-audit.md`

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: фиксация исходного состояния («база») как критерия «до/после»

- [ ] T001 Сверить базовое состояние с таблицей «Baseline Audit» в specs/002-constitution-refactor/spec.md: `uv run pytest` (ожидается 67 passed, coverage 86%) и `ruff check src tests` (ожидается 14 ошибок: 5 в src + 9 в tests); при расхождении — остановиться и разобраться, прежде чем менять что-либо (quickstart.md §3)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: срез S1 (research.md R10) — шлюз статического анализа реально работает по `src/` **и** `tests/` (B9, B10; FR-006, FR-009). Без него «зелёный ruff» на срезах последующих фаз не проверяем

**⚠️ CRITICAL**: пользовательские истории не начинаются, пока эта фаза не завершена

- [ ] T002 В pyproject.toml убрать `"tests"` из `[tool.ruff] exclude` (оставить `".venv"`, `"alembic"`); прочие секции — без изменений
- [ ] T003 [P] src/ai_detector/__init__.py — отсортировать `__all__` по алфавиту (RUF022)
- [ ] T004 [P] src/ai_detector/_spawn.py — SIM105 ×2: заменить `try/except BaseException: pass` на `contextlib.suppress(BaseException)` (ветки `_settle_spawn_task` и `_reap_spawn_task`)
- [ ] T005 [P] src/ai_detector/code_aggregator.py — B905: `zip(relative_paths, contents, strict=True)` (списки равной длины — инвариант `asyncio.gather`)
- [ ] T006 [P] src/ai_detector/repo_cloner.py — UP041: сохранить кортеж `(TimeoutError, asyncio.TimeoutError)` (на Python 3.10 — разные классы), добавить целевой `# noqa: UP041` с комментарием-обоснованием (research.md R5)
- [ ] T007 [P] tests/unit/test_code_aggregator.py — E501: перенести строку документ-стринга (line 1)
- [ ] T008 [P] tests/unit/test_git_metadata.py — UP012: убрать явный `"utf-8"` у `str.encode()` (line 83)
- [ ] T009 tests/unit/test_repo_cloner.py — UP012 ×2 (lines 187, 261) + I001 (порядок импортов, line 253) + ASYNC110: polling-цикл `while + await asyncio.sleep(0.005)` (line 226) заменить ожиданием `asyncio.Event`, который фейк выставляет при наступлении ожидаемого условия; смысл ассертов не менять
- [ ] T010 [P] tests/unit/test_service.py — E501 (line 205: перенести строку документ-стринга) + ASYNC110: polling-цикл (line 139) заменить ожиданием `asyncio.Event`, выставляемого фейками при старте обеих операций; сохранение смысла: «обе стартовали до завершения любой»
- [ ] T011 [P] tests/integration/test_cancellation_regression.py — F401: удалить неиспользуемый импорт `spawn_git` (line 42)
- [ ] T012 Верификация среза S1: `uv run ruff check src tests` → 0 нарушений; `uv run pytest` → 67 passed, coverage ≥ 86% (FR-006, FR-009, SC-002)

**Checkpoint**: шлюз работает — каждый последующий срез обязан держать ruff = 0 по обоим каталогам

---

## Phase 3: User Story 1 - Ядро пакета соответствует Уставу без изменения поведения (Priority: P1) 🎯 MVP

**Goal**: исходный код пакета приведён к принципам I/IV/V (и улучшению по I: строгая типизация) — B1, B2, B3, B4, B5, B8 устранены; наблюдаемое поведение публичного API идентично (FR-001, FR-002, FR-003, FR-005)

**Independent Test**: `uv run pytest` — все тесты зелёны, публичный экспорт/иерархия исключений/схема вердикта не изменились; `git status --short demo/ README.md` — пусто; ruff = 0

### Implementation for User Story 1

- [ ] T013 [US1] src/ai_detector/_spawn.py — добавить два чистых хелпера (research.md R1): `git_stderr_tail(stderr: bytes, limit: int = 3) -> str` (decode utf-8/replace → splitlines → последние N → «stderr git пуст») и `git_spawn_failure_message(operation: str, exc: OSError) -> str` (шаблон «Не удалось запустить git … (проверьте, что git CLI установлен и доступен в PATH): {exc}»); словесный состав — дословно как в текущих реализациях
- [ ] T014 [US1] src/ai_detector/_spawn.py — (зависит: T013) ввести приватный класс `_GitSpawnSupervisor` (R2): `SETTLE_TIMEOUT_SECONDS: ClassVar[float] = 2.0` и `_REAPERS: ClassVar[set[asyncio.Task[None]]] = set()` (done-колбэк — `discard`); `_settle_spawn_task`/`_reap_spawn_task` → classmethod'ы; `spawn_git(*argv)` — тонкая обёртка, сигнатура сохранена; модульных глобалов в модуле не остаётся (кроме самого класса)
- [ ] T015 [US1] src/ai_detector/repo_cloner.py — (зависит: T013) R1+R3: убрать `_stderr_tail`, OSError-обёртка → `git_spawn_failure_message`, хвост stderr в `_clone_failure_message` → `git_stderr_tail`; константы `CLONE_TIMEOUT_SECONDS`, `_GITHUB_HOSTS`, `_ACCESS_FAILURE_MARKERS` → `ClassVar` класса `RepoCloner`; тексты ошибок — без изменений
- [ ] T016 [P] [US1] src/ai_detector/git_metadata.py — (зависит: T013) R1+R3: убрать `_git_error_detail` (префикс «{command} завершился с кодом {returncode}:» сохранить в `_run_git`), хвост stderr → `git_stderr_tail`; константы `COMMIT_LOG_FORMAT`, `_FIELD_SEPARATOR` → `ClassVar` класса `GitMetadataExtractor`
- [ ] T017 [P] [US1] src/ai_detector/code_aggregator.py — R3: `SUPPORTED_EXTENSIONS`, `EXCLUDED_DIRS`, `MAX_CONCURRENT_READS` → `ClassVar` класса `LocalCodeAggregator` (default-аргумент `__init__` читает атрибут класса)
- [ ] T018 [P] [US1] src/ai_detector/llm_judge.py — R3+R4: `DEFAULT_LLM_MODEL` и `MAX_ATTEMPTS` → `ClassVar` (декоратор `@retry` читает атрибут без изменения значения); заменить `return parsed  # type: ignore[return-value]` на типизированную границу: `parsed is None` — прежняя ветка `_TransientLLMError`; `not isinstance(parsed, AIAssessmentResult)` → `LLMJudgementError` (fail-loud); `# type: ignore` удалён, `Any` в пакете отсутствует
- [ ] T019 [P] [US1] src/ai_detector/utils/models.py — R3: `COMMIT_HASH_PATTERN` → `ClassVar[str]` на `CommitInfo`; `Field(pattern=...)` ссылается на атрибут класса (pydantic v2 не считает ClassVar полем — схема `AIAssessmentResult`/`CommitInfo` вне рамок изменений не меняется)
- [ ] T020 [US1] (зависит: T013–T019) адаптировать тесты к новым внутренним местам: тесты/unit/test_repo_cloner.py, tests/unit/test_git_metadata.py, tests/unit/test_code_aggregator.py, tests/unit/test_llm_judge.py, tests/unit/test_models.py — обновить импорты/ссылки на перенесённые константы и хелперы; смысл проверяемых ассертов — без изменений
- [ ] T021 [US1] (зависит: T020) Верификация US1: `uv run ruff check src tests` → 0; `uv run pytest` → ≥67 passed, coverage ≥ 86%; `git status --short demo/ README.md` → пусто (FR-001, FR-002, FR-003, FR-005, FR-009, SC-001, SC-005)

**Checkpoint**: MVP — «пакет чист, поведение то же»: US1 полностью функционален и проверяется независимо

---

## Phase 4: User Story 2 - Шлюзы качества работают как объявлено в Уставе (Priority: P2)

**Goal**: покрываемость не ниже базовой, публичные методы покрыты включая задокументированные ветки отмены `spawn_git` (B11; FR-008, SC-001, SC-004)

**Independent Test**: `uv run pytest` — все тесты (включая новые) зелёны; суммарное покрытие ≥ 86%; модуль `src/ai_detector/_spawn.py` ≥ 90%; ruff = 0

### Tests for User Story 2

> Задачи фиксируют существующее поведение (regression-pinning) — зелёны с первого запуска

- [ ] T022 [US2] tests/unit/test_spawn.py (новый файл) — юнит-тесты непокрытых веток `src/ai_detector/_spawn.py` (research.md R8): (a) двойная отмена вызывающего в окне settle → второй `cancel()` осевшей spawn-задачи, kill процесса, `CancelledError` проброшен, осиротевших задач нет; (b) spawn-задача не оседает до `SETTLE_TIMEOUT_SECONDS` → ветка «второй cancel» + `None`; (c) «сборщик»: reaper осаживает spawn-задачу, убивает процесс, дожидается, удаляет себя из ClassVar-реестра (done-колбэк); (d) сбой запуска проигрывает отмене (spawn-задача с исключением → `None`, отмена проброшена). Фейки — классы уровня модуля со счётчиками `kill()`/`wait()` (паттерн R6); цель: покрытие `_spawn.py` ≥ 90%

### Implementation for User Story 2

- [ ] T023 [US2] (зависит: T022) Верификация US2: `uv run pytest` → все зелёны (≥ 67 + новые тесты), суммарное покрытие ≥ 86%, `src/ai_detector/_spawn.py` ≥ 90% (шлюз 30% пройден); `uv run ruff check src tests` → 0 (FR-008, SC-001, SC-004)

**Checkpoint**: US1 + US2 работают независимо; качество зафиксировано шлюзами

---

## Phase 5: User Story 3 - Код тестов подчинён тем же принципам (Priority: P2)

**Goal**: тесты — DRY (B7), без вложенных функций (B6), ruff-чистые (FR-004, FR-007); множество поведенческих проверок не сокращается

**Independent Test**: каждый дублирующийся помощник — одно определение; AST-проверка вложенных FunctionDef в `tests/` — 0 за пределами обоснованных одноразовых замыканий; ruff по `tests/` = 0; все поведенческие ассерты сохранены

### Implementation for User Story 3

- [ ] T024 [US3] tests/helpers.py (новый файл) — research.md R7: единственные определения `detector_temp_dirs() -> set[str]` (перечисление temp-каталогов детектора, префикс «ai-detector-»), `git_run(repo: Path, *args: str) -> None` (subprocess git для локальных репозиториев) и `make_result(status: str = "green", **overrides: object) -> AIAssessmentResult` (объединённая сигнатура двух локальных `make_result`)
- [ ] T025 [P] [US3] tests/unit/test_service.py — (зависит: T024) R6 + R7: локальные фейки (`FailingExtractor`, `EmptyHistoryExtractor`, `FailingCloneProcess`, `failing_spawn`) вынести на уровень модуля (классы с явным конструктором / вызывающий объект с `async def __call__`); убрать локальные `_detector_temp_dirs` и `make_result` → импорты из `tests/helpers.py`; семантика тестов — без изменений
- [ ] T026 [P] [US3] tests/unit/test_repo_cloner.py — (зависит: T024) R6: локальные фейки и вложенные функции (`ClonerHarness`-обвязка, `body()`-колбэк, вложенные классы в тестах маскирования/отмены) вынести на уровень модуля с явными аргументами; `functools.partial` на модульные функции допустим как связующий объект
- [ ] T027 [P] [US3] tests/unit/test_llm_judge.py — (зависит: T024) R7: убрать локальный `make_result` → импорт из `tests/helpers.py` (при необходимости — расширить дефолты помощника, не меняя ассерты)
- [ ] T028 [P] [US3] tests/unit/test_git_metadata.py — (зависит: T024) R6: локальные фейк-классы и `raising_spawn` вынести на уровень модуля с явными аргументами
- [ ] T029 [P] [US3] tests/integration/test_cancellation_regression.py — (зависит: T024) R6 + R7: вложенные функции (`spawner`, `failer`-обвязка) вынести на уровень модуля; убрать локальные `_detector_temp_dirs` и `_git` → импорты `detector_temp_dirs`/`git_run` из `tests/helpers.py`
- [ ] T030 [P] [US3] tests/integration/test_pipeline_smoke.py — (зависит: T024) R6 + R7: локальные фейк-классы (`FakeCompletions` и обвязка), `dead_parse`, `_sleep` вынести на уровень модуля; убрать локальный `_git` → импорт `git_run` из `tests/helpers.py`
- [ ] T031 [US3] (зависит: T025–T030) Верификация US3: `uv run ruff check src tests` → 0; AST-проверка `tests/`: FunctionDef/AsyncFunctionDef внутри функции — 0 за пределами одноразовых замыканий (каждое такое замыкание — с комментарием-обоснованием по принципу VI); `uv run pytest` → все зелёны; `git diff` по `tests/` подтверждает: число поведенческих ассертов не сократилось (FR-004, FR-007, SC-002)

**Checkpoint**: US1 + US2 + US3 независимы; код тестов соответствует принципам

---

## Phase 6: User Story 4 - Аудит соответствия воспроизводим и зафиксирован (Priority: P3)

**Goal**: воспроизводимый артефакт аудита: скрипт (stdlib-only) + markdown-отчёт по принципу → статус → доказательство → обоснование (FR-010, SC-003; контракт — contracts/audit-report.md)

**Independent Test**: `uv run python scripts/compliance_audit.py` → exit 0; `docs/compliance-audit.md` соответствует контракту формата; повторный запуск при неизменном коде — идентичный отчёт

### Implementation for User Story 4

- [ ] T032 [US4] scripts/compliance_audit.py (новый файл) — research.md R9 + contracts/audit-report.md: stdlib-only (`ast`, `pathlib`, `subprocess`, `json`, `datetime`); проверки: I (0 `# type: ignore`/`Any` в `src/` без обоснования), II (`LLMJudge`: `beta.chat.completions.parse`, `response_format=`, `temperature=0`; нет raw-text-`re.`-поиска по LLM-ответу), III (покрытие из запуска pytest: публичные методы, `_spawn.py` ≥ 90%), IV (отрицательные проверки дублей B1/B2/B7: старые имена определений — 0 вхождений; shared-хелперы R1/R7 — ровно 1 определение), V (AST `src/`: модульные assignments — мутатные = deviation, immutable = сверка с allowlist-таблицей в скрипте со строкой-обоснованием), VI (AST `src/`+`tests/`: вложенные FunctionDef/AsyncFunctionDef — сверка с allowlist одноразовых замыканий), Technology Stack (0 новых runtime-зависимостей vs `pyproject.toml`), Development Workflow (запуск ruff → 0 и pytest → green/≥86%, краткий вывод в отчёт); exit codes 0/1/2; полный перезаписывающий генератор отчёта
- [ ] T033 [US4] (зависит: T032) сгенерировать и зафиксировать отчёт: `uv run python scripts/compliance_audit.py` → exit 0; `docs/compliance-audit.md` создан: все 8 блоков со статусами, каждая `deviation`-строка имеет запись в «Обоснованных отклонениях» (иначе exit 1 и доработка allowlist/кода); повторный запуск — идентичный отчёт (идемпотентность, контракт §5)

**Checkpoint**: все user stories функциональны; соответствие Уставу — верифицируемое свойство

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: финальная сквозная валидация фичи по quickstart.md и гигиена diff

- [ ] T034 [P] Прогнать сценарии quickstart.md С1–С5 — все ожидаемые исходы: ruff 0 (src+tests, без `"tests"` в exclude); pytest ≥ 67 passed + coverage ≥ 86% (+ `_spawn.py` ≥ 90%); аудит exit 0; `git status --short demo/ README.md` — пусто; интеграционный смоук `tests/integration/test_pipeline_smoke.py` — зелёный; проверки дедупликации (S5)
- [ ] T035 [P] Гигиена изменения: `git status --short` + `git diff --name-only` — набор изменённых файлов соответствует ожидаемому: `pyproject.toml`, модули `src/ai_detector/`, `tests/**` (+ `tests/helpers.py`), `scripts/compliance_audit.py`, `docs/compliance-audit.md`; `demo/`, `README.md`, `docs/architecture.md`, артефакты фичи 001 — без изменений; вне gitignore не осталось лишних артефактов (SC-005, SC-006)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: без зависимостей — стартовать немедленно
- **Foundational (Phase 2)**: зависит от Setup; **БЛОКИРУЕТ** все user story (без шлюза срезы FR-009 не проверяемы)
- **User Story 1 (Phase 3)**: после Foundational — первая по приоритету (P1, MVP)
- **User Story 2 (Phase 4)**: после US1 (тесты целятся в финальную структуру `_spawn.py` из T014)
- **User Story 3 (Phase 5)**: после US1 (T020 уже адаптировал тесты к перенесённым местам); **параллельна US2** (непересекающиеся файлы: US2 создаёт `tests/unit/test_spawn.py`, US3 правит существующие тест-файлы)
- **User Story 4 (Phase 6)**: после US2+US3 (аудирует финальное состояние кода)
- **Polish (Phase 7)**: после всех user story

### User Story Dependencies

- **US1 (P1)**: старт после Foundational; не зависит от других историй
- **US2 (P2)**: старт после US1; независимо тестируется
- **US3 (P2)**: старт после US1; независимо тестируема; параллельна US2
- **US4 (P3)**: старт после US2+US3; независимо тестируется (своя команда и артефакт)

### Within Each User Story

- Рефакторинг поведенчески-нейтрален: тесты существуют заранее (regression-pinning, а не TDD-«красный-зелёный»); единственные новые тесты (T022) фиксируют текущее поведение
- Хелперы/владельцы состояния (T013, T014, T024) — до их потребителей (T015–T020, T025–T030)
- Задачи по одному файлу последовательны; [P] — только разные файлы
- Задача верификации (последняя в фазе) обязательна до перехода к следующей фазе (FR-009)

### Parallel Opportunities

- Phase 2: T003–T011 — все [P], запускать вместе (9 файлов, нет пересечений)
- Phase 3: после T013–T014 параллельно T015, T016, T017, T018, T019 (5 разных файлов); затем T020 → T021
- Phase 4 ∥ Phase 5: US2 (T022–T023) и US3 (T024–T031) — параллельно при наличии двух исполнителей (непересекающиеся файлы)
- Phase 5: после T024 параллельно T025–T030 (6 разных файлов)
- Phase 7: T034 и T035 — параллельно

---

## Parallel Example: User Story 1

```bash
# Сначала (последовательно, один файл):
Task: "T013 src/ai_detector/_spawn.py — хелперы git_stderr_tail/git_spawn_failure_message"
Task: "T014 src/ai_detector/_spawn.py — _GitSpawnSupervisor (ClassVar-состояние)"

# Затем — параллельно (разные файлы):
Task: "T015 src/ai_detector/repo_cloner.py — R1+R3"
Task: "T016 src/ai_detector/git_metadata.py — R1+R3"
Task: "T017 src/ai_detector/code_aggregator.py — R3"
Task: "T018 src/ai_detector/llm_judge.py — R3+R4"
Task: "T019 src/ai_detector/utils/models.py — R3"
```

## Parallel Example: User Story 3

```bash
# Сначала:
Task: "T024 tests/helpers.py — detector_temp_dirs/git_run/make_result"

# Затем — параллельно (разные файлы):
Task: "T025 tests/unit/test_service.py — R6+R7"
Task: "T026 tests/unit/test_repo_cloner.py — R6"
Task: "T027 tests/unit/test_llm_judge.py — R7"
Task: "T028 tests/unit/test_git_metadata.py — R6"
Task: "T029 tests/integration/test_cancellation_regression.py — R6+R7"
Task: "T030 tests/integration/test_pipeline_smoke.py — R6+R7"
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (сверка базы)
2. Complete Phase 2: Foundational (CRITICAL — блокирует все истории)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: T021 — pytest зелёный, ruff 0, потребителям 0 правок
5. MVP достижим: «пакет чист, поведение то же» (US1)

### Incremental Delivery

1. Setup + Foundational → шлюз работает
2. US1 → верификация T021 (MVP!)
3. US2 ∥ US3 → верификации T023/T031
4. US4 → верификация T033 (аудит green)
5. Polish → T034–T035 (quickstart С1–С5, гигиена diff)
6. Каждый срез инкрементален: зелёные тесты + ruff 0 (FR-009, SC-006)

### Parallel Team Strategy

При двух исполнителях:

1. Оба выполняют Setup + Foundational (Phase 1–2, задачи T003–T011 — параллельно по файлам)
2. Оба выполняют US1 (Phase 3: параллельные T015–T019)
3. Затем: Исполнитель A → US2 (Phase 4), Исполнитель B → US3 (Phase 5) — параллельно, непересекающиеся файлы
4. Собираются на US4 (Phase 6) — один исполнитель
5. Polish (Phase 7) — оба (T034 ∥ T035)

## Notes

- [P] = разные файлы, нет зависимостей на незавершённые задачи
- [Story] label — трассировка задачи к user story
- Каждая фаза завершается задачей верификации (шлюзы FR-009) — переход без неё запрещён
- Публичный контракт заморожен (FR-001): при любом конфликте «принцип vs поведение» побеждает поведение — см. spec.md → Edge Cases
- Токсичные для git-статуса артефакты (.coverage, htmlcov/) — в gitignore, на T035 не влияют
- После выполнения всех фаз: `/speckit-converge` должен завершаться `converged` (quickstart.md §5)
