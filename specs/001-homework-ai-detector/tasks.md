# Tasks: Homework AI Detector

**Input**: Design documents from `/specs/001-homework-ai-detector/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Requested — конституция §4 требует `pytest` + `pytest-asyncio` для всех public-методов с моками `asyncio.create_subprocess_exec`, файлового I/O и `AsyncOpenAI`; quickstart.md §3–4 задаёт сценарии. Тестовые задачи включены, подход TDD: тесты пишутся первыми и должны **провалиться** до реализации.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project** (src-layout, research.md §1): `src/ai_detector/`, `tests/` at repository root
- Конфигурация проекта — `pyproject.toml` + `uv.lock` (только через `uv sync`)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [X] T001 [P] Create project structure per plan.md: directories `src/ai_detector/`, `tests/unit/`, `tests/integration/` and placeholder `src/ai_detector/__init__.py`
- [X] T002 [P] Create `pyproject.toml`: `[build-system]` hatchling; `[project]` name `ai-detector`, `requires-python = ">=3.10"`, dependencies `pydantic>=2`, `openai>=1.40`, `aiofiles`, `tenacity`, `httpx`; dev-группа `pytest`, `pytest-asyncio`; `[tool.pytest.ini_options]` c `asyncio_mode = "auto"` и `testpaths = ["tests"]` (research.md §1)
- [X] T003 Run `uv sync` (создаст `.venv` и `uv.lock`) and verify environment per quickstart.md §1–2: `uv run python --version`, `uv run pytest --version`, `git --version`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 [P] Implement exception hierarchy in `src/ai_detector/exceptions.py`: base `AIDetectionError(Exception)` → `RepoCloneError`, `MetadataExtractionError`, `CodeAggregationError`, `LLMJudgementError`; сообщения — человекочитаемые, на русском, без токена доступа (research.md §11, data-model.md §5)
- [X] T005 [P] Implement pydantic v2 models in `src/ai_detector/models.py`: `CommitInfo` (`hash` — `str` pattern `^[0-9a-f]{40}$`, `author` — непустой `str`, `date` — `str` ISO 8601 с таймзоной, `message` — однострочный `str`) и `AIAssessmentResult` (`status: Literal["green", "yellow", "red"]`, `confidence: float` c `ge=0.0, le=1.0`, `reasoning: str`, `ai_indicators: list[str]`, `human_indicators: list[str]`); поле `task_compliance_score` в схеме **не существует** (FR-009); строгие type hints, без `Any` (data-model.md §1, §4)
- [X] T006 Implement prompt templates in `src/ai_detector/prompts.py`: `SYSTEM_PROMPT` (дословно ТЗ §5 / contracts/llm-structured-output.md §3 + контрактные дополнения: обоснование и списки признаков — на русском, поле `task_compliance_score` не заполнять) и `USER_PROMPT_TEMPLATE` (3 блока: КРИТЕРИИ ЗАДАНИЯ / МЕТАДАННЫЕ РЕПОЗИТОРИЯ (структура файлов + история коммитов) / ПОЛНЫЙ ИСХОДНЫЙ КОД — §4); функции `format_commit_history(commits: list[CommitInfo]) -> str` (по строке на коммит: `<hash[0..7]> | <date ISO> | <author> | <message>`) и `format_file_tree(file_tree: list[str]) -> str` (depends on T005)

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Базовый анализ репозитория с решением (Priority: P1) 🎯 MVP

**Goal**: Один вызов `AIDetectionService.analyze(task_criteria, repo_url)` для публичного репозитория: локальный `git clone` → **параллельный** сбор полной истории коммитов и полного исходного кода → оценка локальной LLM через Structured Output → валидированный вердикт `AIAssessmentResult` (green/yellow/red).

**Independent Test**: На фикстурном локальном репозитории (реальные `git init`/коммиты в tmp + `git clone`) с мок `AsyncOpenAI` метод `analyze()` возвращает полный `AIAssessmentResult` (все 5 полей), а temp-каталоги не остаются (запуск: `uv run pytest tests/integration -v`).

### Tests for User Story 1 (write FIRST, ensure they FAIL) ⚠️

- [X] T007 [P] [US1] Write unit tests in `tests/unit/test_repo_cloner.py` (мок `asyncio.create_subprocess_exec`): `git clone` запускается как асинхронный subprocess; `returncode != 0` → `RepoCloneError` с хвостом stderr; таймаут клонирования (120 c, `asyncio.wait_for`) → `RepoCloneError`; temp-каталог удалён после нормального выхода из `async with` (FR-002, FR-010)
- [X] T008 [P] [US1] Write unit tests in `tests/unit/test_git_metadata.py` (мок subprocess): JSON-история парсится в `list[CommitInfo]` с валидными полями; команда содержит точно `--pretty=format:'{"hash":"%H","author":"%an","date":"%aI","message":"%s"}' --no-merges` (merge-коммиты отсутствуют — FR-003); строка, не являющаяся JSON → `MetadataExtractionError` с идентификатором строки (fail-loud); `git ls-files` → полное дерево файлов (research.md §4–5)
- [X] T009 [P] [US1] Write unit tests in `tests/unit/test_code_aggregator.py` (фикстуры `tmp_path`): whitelist расширений {`.py`, `.go`, `.rs`, `.js`, `.ts`, `.java`, `.cpp`, `.md`} и blacklist директорий {`.git`, `__pycache__`, `venv`, `node_modules`, `.idea`, `.vscode`} соблюдены (FR-005); маркеры `--- FILE: <path> ---` / `--- END FILE ---` на месте; содержимое **полное**, без усечения (FR-004); чтения ограничены `asyncio.Semaphore(20)`; ни одного поддерживаемого файла → `CodeAggregationError` с сообщением «no supported source files» (FR-013)
- [X] T010 [P] [US1] Write unit tests in `tests/unit/test_llm_judge.py` (мок `AsyncOpenAI`): вызов идёт через `client.beta.chat.completions.parse` c `response_format=AIAssessmentResult` и `temperature=0`; временные сбои (`APITimeoutError`, `APIConnectionError`, `RateLimitError`, `APIStatusError` 5xx) повторяются автоматически не более 3 раз (tenacity, `wait_exponential(min=1, max=10)`); `parsed is None` → `LLMJudgementError`; результат читается только из `.choices[0].message.parsed`; модель берётся из `AI_DETECTOR_LLM_MODEL` или константы по умолчанию (FR-008, FR-012; research.md §8–9)
- [X] T011 [P] [US1] Write unit tests in `tests/unit/test_service.py` (моки cloner/extractor/aggregator/judge): `AIDetectionService.__init__(llm_client)` — чистая сборка подсистем без I/O и без чтения окружения; `analyze` собирает метаданные и код **параллельно** через `asyncio.gather` (FR-006 — проверить пересечение во времени запуска моков); в LLM уходят критерии + структура файлов + история коммитов + полный код (FR-007); happy path → полный `AIAssessmentResult`; исключение внутри пайплайна → временный клон гарантированно удалён (FR-010)

> **NOTE**: all T007–T011 must FAIL (ImportError/несуществующие модули) before implementation.

### Implementation for User Story 1

- [X] T012 [P] [US1] Implement `RepoCloner` in `src/ai_detector/repo_cloner.py`: `clone(repo_url: str)` — `@asynccontextmanager`, создаёт `tempfile.TemporaryDirectory`, выполняет `git clone <url> <dir>` через `asyncio.create_subprocess_exec`, `returncode != 0` → `RepoCloneError` (причина на русском + хвост stderr), `asyncio.wait_for(..., 120)` (константа) → `RepoCloneError`, в `finally` — `TemporaryDirectory.cleanup()` **до** выхода, т.е. гарантированно при любом исключении тела (research.md §2; FR-002, FR-010)
- [X] T013 [P] [US1] Implement `GitMetadataExtractor` in `src/ai_detector/git_metadata.py`: `async def extract(self, repo_path: Path) -> tuple[list[CommitInfo], list[str]]` — `git log` с командой точно по ТЗ §4.3 (research.md §4), вывод читается построчно, каждая строка → `json.loads` → `CommitInfo`, невалидная строка → `MetadataExtractionError` (fail-loud); `git ls-files` (stdout построчно) → полное дерево файлов HEAD (research.md §5); строгая типизация, без `Any` (FR-002, FR-003)
- [X] T014 [P] [US1] Implement `LocalCodeAggregator` in `src/ai_detector/code_aggregator.py`: `async def aggregate(self, repo_path: Path) -> str` — `Path.rglob("*")`, отбор по whitelist расширений {`.py`, `.go`, `.rs`, `.js`, `.ts`, `.java`, `.cpp`, `.md`} и blacklist директорий {`.git`, `__pycache__`, `venv`, `node_modules`, `.idea`, `.vscode`}, чтение через `aiofiles` (UTF-8; не-UTF8 файл — пропуск с warning в лог), `asyncio.Semaphore(20)` (константа), результат — одна строка с маркерами `--- FILE: <path> ---` … `--- END FILE ---`; пустой результат → `CodeAggregationError("no supported source files")` (research.md §6; FR-004, FR-005, FR-014)
- [X] T015 [P] [US1] Implement `LLMJudge` in `src/ai_detector/llm_judge.py`: `__init__(self, client: AsyncOpenAI) -> None`; `async def evaluate(self, task_criteria: str, file_tree: list[str], commits: list[CommitInfo], full_code: str) -> AIAssessmentResult` — `client.beta.chat.completions.parse(model=..., messages=[system, user], response_format=AIAssessmentResult, temperature=0)` c промптами из `src/ai_detector/prompts.py`; результат только `response.choices[0].message.parsed`, `parsed is None` → `LLMJudgementError`; `@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), reraise=True)` c множеством повторов: `openai.APITimeoutError`, `openai.APIConnectionError`, `openai.RateLimitError`, `openai.APIStatusError` со `status_code >= 500`, `LLMJudgementError`; модель — `AI_DETECTOR_LLM_MODEL` или константа по умолчанию (research.md §8–9; FR-008, FR-012)
- [X] T016 [US1] Implement facade `AIDetectionService` in `src/ai_detector/service.py`: `__init__(self, llm_client: AsyncOpenAI) -> None` — чистая сборка `RepoCloner`, `GitMetadataExtractor`, `LocalCodeAggregator`, `LLMJudge(llm_client)` (конструктор не читает окружение); `async def analyze(self, task_criteria: str, repo_url: str) -> AIAssessmentResult` — внутри `async with RepoCloner().clone(repo_url) as repo_path`: `await asyncio.gather(extractor.extract(repo_path), aggregator.aggregate(repo_path))` → заполнение `USER_PROMPT_TEMPLATE` → `judge.evaluate(...)`; наружу пробрасывается только иерархия `AIDetectionError` (contracts/public-api.md §2; FR-001, FR-006, FR-007, FR-013)
- [X] T017 [US1] Implement public exports in `src/ai_detector/__init__.py`: `AIDetectionService`, `AIAssessmentResult`, `CommitInfo`, `AIDetectionError`, `RepoCloneError`, `MetadataExtractionError`, `CodeAggregationError`, `LLMJudgementError` (contracts/public-api.md §1)
- [X] T018 [US1] Implement integration smoke test in `tests/integration/test_pipeline_smoke.py`: фикстурный репозиторий (в `tmp_path`: `git init` + несколько коммитов с `.py`-файлами) + реальный `git clone` (локальный путь/`file://`) + мок `AsyncOpenAI` (возвращает валидный structured-ответ) → `AIDetectionService.analyze(...)` возвращает полный `AIAssessmentResult`; после вызова temp-каталоги не остаются (SC-004) (quickstart.md §4)

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently (MVP: публичный репозиторий → полный вердикт, временные данные очищены)

---

## Phase 4: User Story 2 - Анализ приватного репозитория (Priority: P2)

**Goal**: Клонирование приватного репозитория по токену из переменных окружения (`GITHUB_TOKEN`, переопределение `AI_DETECTOR_GIT_TOKEN`) без токена в URL/конфигах/коде; при отсутствии токена — понятная ошибка, а не молчаливый сбой.

**Independent Test**: Мок-проверки в `tests/unit/test_repo_cloner.py`: токен подставлен в аргумент subprocess как `x-access-token` и **отсутствует** в сообщении ошибки; сценарий «приватный URL без токена» → `RepoCloneError` с чётким сообщением о правах (запуск: `uv run pytest tests/unit/test_repo_cloner.py -v`).

### Tests for User Story 2 (write FIRST, ensure they FAIL) ⚠️

- [ ] T019 [P] [US2] Extend unit tests in `tests/unit/test_repo_cloner.py` (мок `asyncio.create_subprocess_exec` + monkeypatch окружения): при выставленном `GITHUB_TOKEN` URL `https://github.com/<owner>/<repo>.git` передан в subprocess как `https://x-access-token:<token>@github.com/...`; `AI_DETECTOR_GIT_TOKEN` имеет приоритет над `GITHUB_TOKEN`; публичный URL без токена не модифицируется; при `RepoCloneError` токен **отсутствует** в `str(exc)` и в логах; приватный репозиторий без токена → `RepoCloneError` о недоступности/правах (FR-011; research.md §3)

### Implementation for User Story 2

- [ ] T020 [US2] Implement token handling in `src/ai_detector/repo_cloner.py`: чтение токена из `GITHUB_TOKEN` (переопределение `AI_DETECTOR_GIT_TOKEN`); при наличии токена и URL `github.com` — внутренняя (только для аргумента subprocess) трансформация в `https://x-access-token:<token>@github.com/<owner>/<repo>.git`; токен нигде не сохраняется и не логируется; хвост stderr в `RepoCloneError` санитизируется (маскирование токена) (research.md §3; FR-011)

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently (публичные и приватные репозитории дают вердикт; без токена — чёткая ошибка)

---

## Phase 5: User Story 3 - Надёжная обработка сбоев и гарантированная очистка (Priority: P3)

**Goal**: Временные сбои LLM устраняются автоматически (≤3 повторов); неисправимые сбои (404, context overflow, недоступный репозиторий, нет кода) дают чёткую доменную ошибку, а не «мусорный» результат; локальная копия репозитория гарантированно удаляется при любом исходе, включая отмену.

**Independent Test**: Имитация мёртвой LLM, 404, context overflow, недоступного репозитория и отмены: в каждом случае — ожидаемое доменное исключение с русским сообщением (без токена) и отсутствие остатков temp-данных (запуск: `uv run pytest tests/ -v`; ручная негативная таблица — quickstart.md §6).

### Tests for User Story 3 (write FIRST, ensure they FAIL) ⚠️

- [ ] T021 [P] [US3] Extend unit tests in `tests/unit/test_llm_judge.py` (мок `AsyncOpenAI`): `openai.NotFoundError` (404, модель/эндпоинт) → немедленный `LLMJudgementError` **без** повторов; context overflow (400, `openai.BadRequestError` про токены/контекст) → `LLMJudgementError` с текстом «объём кода превышает вместимость модели; усечение запрещено» **без** повторов и без усечения (FR-004); устойчивый сбой (мёртвый порт) → `LLMJudgementError` «повторы исчерпаны» после ровно 3 попыток (FR-012, FR-013, SC-006; contracts/llm-structured-output.md §6)
- [ ] T022 [P] [US3] Extend unit tests in `tests/unit/test_repo_cloner.py`: при `asyncio.CancelledError` и при произвольном исключении в теле `async with` temp-каталог гарантированно удалён (SC-004); хвост stderr в `RepoCloneError` не содержит токен (если тот присутствовал в URL) (FR-010)
- [ ] T023 [P] [US3] Extend unit tests in `tests/unit/test_service.py`: наружу из `analyze` пробрасывается **только** иерархия `AIDetectionError` (низкоуровневые `OSError`/сбои subprocess маппируются в доменные исключения); сообщения ошибок — на русском, без токена и без обязательного пути к temp-каталогу (FR-013, contracts/public-api.md §3); дегенеративный случай — пустая история коммитов (0 не-merge коммитов): анализ продолжается, история в промпте пуста; сетевой сбой в середине клонирования → `RepoCloneError` + очистка

### Implementation for User Story 3

- [ ] T024 [US3] Refine failure classification in `src/ai_detector/llm_judge.py` per the table in contracts/llm-structured-output.md §6: retry-множество содержит только временные сбои (`APITimeoutError`, `APIConnectionError`, `RateLimitError`, `APIStatusError` 5xx, `LLMJudgementError`); `NotFound` (404) и context overflow (400) → немедленный `LLMJudgementError` c чётким русским сообщением; усечение кода исключено во всех ветках (FR-004, FR-013)
- [ ] T025 [US3] Implement low-level failure mapping in `src/ai_detector/git_metadata.py` and `src/ai_detector/code_aggregator.py`: сбой subprocess (returncode ≠ 0, таймаут) и `OSError` при чтении файлов оборачиваются в `MetadataExtractionError` / `CodeAggregationError` соответственно с русским сообщением; не-UTF8 файл — пропуск с warning в лог, а не сбой (FR-013; data-model.md §5)
- [ ] T026 [US3] Extend integration tests in `tests/integration/test_pipeline_smoke.py` with negative scenarios from quickstart.md §6: несуществующий URL → `RepoCloneError` с русским сообщением; репозиторий без поддерживаемого кода (только изображения) → `CodeAggregationError` «no supported source files»; мёртвый LLM-порт (мок-клиент с `APIConnectionError`) → `LLMJudgementError` после 3 повторов; во всех сценариях следов клона в temp-каталогах не остаётся (SC-004, SC-006)

**Checkpoint**: All user stories should now be independently functional (успех → полный вердикт; любой сбой → чёткая доменная ошибка; temp-данные удалены всегда)

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T027 [P] Create `README.md` at repository root: назначение модуля, prerequisites (Python ≥ 3.10, `uv`, `git` CLI, локальный LLM-сервер c Structured Output), установка `uv sync`, пример использования (contracts/public-api.md §5), таблица переменных окружения (`GITHUB_TOKEN` / `AI_DETECTOR_GIT_TOKEN` / `AI_DETECTOR_LLM_MODEL`), таблица исключений (contracts/public-api.md §3)
- [ ] T028 Run full validation per quickstart.md §7: `uv sync && uv run pytest -v` — весь набор (unit + integration) зелёный; убедиться, что `task_compliance_score` отсутствует в `AIAssessmentResult.model_fields` (FR-009), и что запрос к LLM (мок-захват сообщения) содержит **полный** код всех поддерживаемых файлов без усечения (FR-004); сверить реализацию с DoD из docs/architecture.md §7 (SOLID/типизация, `asyncio.gather`, контекстный менеджер `RepoCloner`, `aiofiles`+`Semaphore`, `parse()`, параллельный сбор)
- [ ] T029 Perform manual end-to-end run per quickstart.md §5 against a real LLM server (vLLM/Triton) on a real public repository: валидный `AIAssessmentResult` (ровно 5 полей), время < 5 минут для ≤20 поддерживаемых файлов (SC-001), отсутствие следов клона после прогона (SC-004), стабильность `status` при повторном прогоне (SC-005); пройтись по негативной таблице quickstart.md §6 (требует доступного LLM-сервера и сети)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion (T003) — BLOCKS all user stories
- **User Stories (Phases 3–5)**: All depend on Foundational phase completion
  - User stories can then proceed in parallel (if staffed) or sequentially in priority order (P1 → P2 → P3)
  - US2 (T020) modifies `src/ai_detector/repo_cloner.py` created in US1 (T012) — не блокирует US1, но требует его завершённости для стабильного diff
  - US3 (T024–T025) уточняет модули US1 (`llm_judge.py`, `git_metadata.py`, `code_aggregator.py`)
- **Polish (Phase 6)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) — no dependencies on other stories
- **User Story 2 (P2)**: Can start after Foundational; builds on `RepoCloner` from US1 (T012) but is independently testable via unit tests
- **User Story 3 (P3)**: Can start after Foundational; refines US1 components, independently testable via failure-path tests

### Within Each User Story

- Tests MUST be written and FAIL before implementation (TDD)
- Models (Phase 2) before services (Phase 3)
- Core components (cloner/extractor/aggregator/judge) before facade `AIDetectionService` (T016)
- Facade + exports (T016–T017) before integration smoke (T018)
- Story complete before moving to next priority

### Parallel Opportunities

- Phase 1: T001 ∥ T002 (different files)
- Phase 2: T004 ∥ T005 (T006 waits on T005)
- US1 tests: T007, T008, T009, T010, T011 — all in parallel (different test files)
- US1 implementation: T012, T013, T014, T015 — all in parallel (different source files, depend only on Phase 2); then T016 → T017 → T018 sequentially
- US3 tests: T021, T022, T023 — in parallel (different test files)
- Phase 6: T027 can run in parallel with the tail of Phase 5
- Different user stories can be worked in parallel by different developers after Phase 2

---

## Parallel Example: User Story 1

```text
# Launch all unit tests for User Story 1 together (TDD, все должны упасть):
Task: "T007 tests/unit/test_repo_cloner.py"
Task: "T008 tests/unit/test_git_metadata.py"
Task: "T009 tests/unit/test_code_aggregator.py"
Task: "T010 tests/unit/test_llm_judge.py"
Task: "T011 tests/unit/test_service.py"

# Launch all core components for User Story 1 together (разные файлы, зависимость только на Phase 2):
Task: "T012 src/ai_detector/repo_cloner.py"
Task: "T013 src/ai_detector/git_metadata.py"
Task: "T014 src/ai_detector/code_aggregator.py"
Task: "T015 src/ai_detector/llm_judge.py"

# Затем последовательно:
Task: "T016 src/ai_detector/service.py" → "T017 src/ai_detector/__init__.py" → "T018 tests/integration/test_pipeline_smoke.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T003)
2. Complete Phase 2: Foundational (T004–T006) — CRITICAL, blocks all stories
3. Complete Phase 3: User Story 1 (T007–T018)
4. **STOP and VALIDATE**: `uv run pytest tests/ -v` зелёный; публичный репозиторий (мок или реальный LLM) → полный вердикт `AIAssessmentResult`
5. Deploy/demo if ready (MVP готов)

### Incremental Delivery

1. Complete Setup + Foundational → foundation ready
2. Add User Story 1 → test independently → MVP (базовый анализ публичного репозитория)
3. Add User Story 2 → test independently → приватные репозитории через токен из окружения
4. Add User Story 3 → test independently → надёжные ошибки и гарантированная очистка при любых сбоях
5. Polish (T027–T029) → README, полная валидация quickstart.md, ручной E2E

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together (T001–T006)
2. Once Foundational is done:
   - Developer A: User Story 1 (T007–T018)
   - Developer B: User Story 2 (T019–T020) — стартует после T012
   - Developer C: User Story 3 (T021–T026) — стартует после T012/T013/T014/T015
3. Stories complete and integrate independently (конфликты в `repo_cloner.py`: US1 сначала, US2 — точечное расширение)

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps task to specific user story for traceability (US1/US2/US3 ← spec.md)
- Each user story should be independently completable and testable
- Verify tests fail before implementing (TDD); `asyncio_mode = "auto"` — ручной `@pytest.mark.asyncio` не требуется
- Commit after each task or logical group
- Stop at any checkpoint to validate the story independently
- Hard constraints (Конституция/TZ): полный код без усечения (FR-004), только `git` CLI без GitHub API (FR-002), `response_format=PydanticModel` без regex-парсинга LLM-текста, `Any` запрещён, гарантированная очистка temp (FR-010), `task_compliance_score` отсутствует (FR-009)
- Avoid: vague tasks, same-file conflicts, cross-story dependencies that break independence
