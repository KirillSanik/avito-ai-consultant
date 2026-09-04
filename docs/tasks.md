# Задачи: объединение ai_detector и homework_reviewer в единый API-сервис

Реализация ТЗ `docs/plan-merge-homework-reviewer-core.md`. Задачи сгруппированы по фазам с учётом зависимостей; внутри фазы пункты можно делать параллельно. В конце — трассировка на критерии приёмки (DoD) из ТЗ §8.

## 0. Анализ текущего состояния (baseline)

Что уже есть:

- **ai_detector**: `AIDetectionService` (фасад), `RepoCloner` (асинхронный контекстный менеджер с гарантированной очисткой temp-каталога), `GitMetadataExtractor`, `LocalCodeAggregator`, `LLMJudge` (AsyncOpenAI + structured output), схемы в `ai_detector/utils/models.py` (`CommitInfo`, `AIAssessmentResult`), промпты в `ai_detector/utils/prompts.py`.
- **homework_reviewer**: `GradingEngine` (синхронный, instructor + OpenAI, режим per-criterion), `TaskParser` (PDF → `TaskRubric` через LLM), парсеры docx/xlsx/links, репозитории отчётов, модели `homework_reviewer/models/{rubric,submission,evaluation}.py`, CLI (`homework-reviewer`).
- **common**: `src/common/config.py` (`AppConfig` на dataclass + `load_dotenv`, env-имена, `git_token`, `limit_input_text`), `src/common/llm/models.py` (каталог бесплатных моделей OpenRouter).
- **main.py**: точка входа uvicorn, но импортирует несуществующий `utils.config` — сломан.
- Тесты: unit (`tests/unit`) и integration (`tests/integration`), покрытие ≥ 30% enforced в pytest addopts; ruff 0.15.14 (line-length 120).

Расхождения с ТЗ (источник задач):

1. Нет `src/app.py` (FastAPI), нет `src/core/pipeline.py`.
2. Нет `src/common/settings.py` на `pydantic-settings` (сейчас dataclass `AppConfig` в `config.py`).
3. Нет единого `src/common/models.py` — схемы разделены между `ai_detector/utils/models.py` и `homework_reviewer/models/`.
4. Нет `src/common/prompts.py` — промпты захардкожены в `ai_detector/utils/prompts.py`, `grading_engine.py`, `task_parser.py`.
5. Нет `src/common/clients.py` / `src/common/llm.py` — клиенты создаются независимо: `AsyncOpenAI` в ai_detector, синхронный `OpenAI`+instructor в `client_factory.py`.
6. `RepoCloner.clone()` — контекстный менеджер с автоудалением; ТЗ требует функцию клонирования **без** автоудаления, очистка — в `Pipeline` (finally после `gather`).
7. `AIDetectionService.analyze()` сам клонирует репозиторий; нет `analyze_from_path(task_criteria, repo_path)`.
8. `GradingEngine` синхронный, работает с `SubmissionData` и пишет в `EvaluationRepository` внутри `evaluate_submission`; нет async `evaluate_from_path(task_criteria, repo_path)`.
9. Парсинг ТЗ (PDF/DOCX/XLSX) разбросан по `homework_reviewer/parsers/` и вызывается внутри `TaskParser.parse_task` вместе с LLM-вызовом; ТЗ требует однократный парсинг в `Pipeline` до `gather`.
10. Отсутствует объединяющая схема `ReviewResponse`.


---

## Фаза 1. Общий слой `src/common/`

### 1.1. Конфигурация
- [ ] Создать `src/common/settings.py` на `pydantic-settings` (`BaseSettings`, чтение `.env`): хост/порт/workers API, провайдер LLM (`openrouter`/`ollama`), имя модели, ключи (`OPENROUTER_API_KEY`), токен git (`GITHUB_TOKEN` / `AI_DETECTOR_GIT_TOKEN`), test_mode.
- [ ] Перенести в `settings.py` поведение из `common/config.py`: `git_token()`, выбор модели, `model_chain` (резервная цепочка из `common/llm/models.py`), `limit_input_text`, `effective_api_base`/`effective_api_key`, `ollama_extra_body`.
- [ ] Обновить импорты во всех потребителях на `common.settings`; `config.py` удалить (или оставить как re-export на время миграции и убрать в конце).

### 1.2. Единые модели
- [ ] Создать `src/common/models.py`:
  - [ ] Перенести `CommitInfo`, `AIAssessmentResult` из `ai_detector/utils/models.py`.
  - [ ] Перенести/реэкспортировать `Criterion`, `TaskRubric`, `Constraints`, `CriterionResult`, `EvaluationReport` (и при необходимости `SubmissionData`).
  - [ ] Добавить `TaskCriteria` — общее представление распарсенного условия (маппинг из `TaskRubric`/текста ТЗ).
  - [ ] Добавить `ReviewResponse` — агрегат: `ai_assessment: AIAssessmentResult` + `evaluation: EvaluationReport` (точный состав зафиксировать при реализации).
- [ ] Удалить дублирующиеся определения из локальных модулей; единственный источник — `src/common/models.py`.

### 1.3. Промпты
- [ ] Создать `src/common/prompts.py`; перенести `SYSTEM_PROMPT`, `USER_PROMPT_TEMPLATE`, `format_commit_history`, `format_file_tree` из `ai_detector/utils/prompts.py`; system/user промпт оценки критерия из `grading_engine.py`; system промпт разбора условия из `task_parser.py`.
- [ ] Убрать строковые промпты из кода модулей — только импорт из `common.prompts`.

### 1.4. Клиенты и LLM-слой
- [ ] Создать `src/common/clients.py`: фабрики `get_llm_client()` (AsyncOpenAI для локального LLM) и `get_openrouter_client()` (для ревьюера), конфигурация из `settings.py`.
- [ ] Создать `src/common/llm.py`: единая обёртка — вызовы API, structured output (instructor / `parse()`), retries (tenacity) на retryable-ошибках (429, 402, таймауты, соединение), 404 → смена модели из `model_chain`, валидация ответа. Перенести сюда `_is_retryable_error` / `_is_model_unavailable` из `GradingEngine` и fallback-логику из `LLMJudge`.
- [ ] Перевести `homework_reviewer` на async-клиентов (предпочтительно async `instructor.from_openai(AsyncOpenAI(...))`).
- [ ] Удалить `evaluator/client_factory.py`.

**Критерий готовности фазы:** модули не содержат собственных схем, промптов и клиентов; unit-тесты зелёные после обновления импортов.

---

## Фаза 2. Вынесение тяжёлых I/O-операций

### 2.1. Клонирование
- [ ] Общая функция `clone_repo(repo_url: str) -> Path` (например, `src/core/repo_clone.py`): **возвращает путь** к локальному клону во временной директории, **без** автоудаления и контекстных менеджеров.
- [ ] Сохранить существующую логику `RepoCloner`: токен (`x-access-token` для github.com), таймаут 120 с, маскирование токена/temp-пути в ошибках, коды возврата git.
- [ ] Адаптировать/заменить `RepoCloner`: контекстный менеджер больше не используется пайплайном.

### 2.2. Парсинг условия
- [ ] Вынести парсинг файла ТЗ (PDF/DOCX/XLSX → текст) в общую функцию/класс (`src/parsers/` или `src/common/parsers/`).
- [ ] Разделить в `TaskParser` два шага: (а) извлечение текста из файла (без LLM) и (б) LLM-структурирование текста в `TaskRubric`/`TaskCriteria`. Пайплайн вызывает оба ровно один раз; внутренние вызовы `TaskParser` из методов оценки удаляются.

**Критерий готовности фазы:** клонирование и парсинг — независимые операции без побочных очисток; покрыты unit-тестами.

---

## Фаза 3. Адаптация модулей под «готовые» входы

### 3.1. ai_detector
- [ ] Добавить `AIDetectionService.analyze_from_path(task_criteria, repo_path: Path) -> AIAssessmentResult`: без клонирования; параллельный сбор метаданных и кода → `LLMJudge.evaluate`. Внутреннее параллельное чтение через `asyncio.gather` с отменой задач при сбое — сохранить.
- [ ] Убрать вызов `RepoCloner` из метода оценки (клонирование делает `Pipeline`).
- [ ] `LLMJudge` перевести на `common.llm` (единый retry/fallback) и `common.prompts`.
- [ ] Перенести схемы/промпты на `common.models` / `common.prompts` (Фаза 1), удалить `ai_detector/utils/models.py`, `ai_detector/utils/prompts.py`.

### 3.2. homework_reviewer
- [ ] Добавить async `GradingEngine.evaluate_from_path(task_criteria, repo_path: Path) -> EvaluationReport`: чтение кода из локального клона, построение `SubmissionData`, оценка по критериям. Без клонирования и парсинга ТЗ.
- [ ] Убрать из метода оценки вызовы `RepoCloner`/`TaskParser` и запись в `EvaluationRepository` (для API-режима сохранение в storage не обязательно; решение зафиксировать на ревью).
- [ ] Перевести на async-клиента из `common.clients` + `common.llm`; убрать `click.echo`/`ClickException` из движка (логирование и исключения; CLI-фасад в `cli.py` остаётся рабочим).
- [ ] Промпты и схемы — из `common.prompts` / `common.models`.
- [ ] Сохранить работоспособность CLI (`homework-reviewer`) на время миграции или явно объявить deprecated в этом PR.

**Критерий готовности фазы:** оба модуля принимают `(task_criteria, repo_path)` и не выполняют клонирование/парсинг ТЗ сами; unit-тесты обновлены и зелёные.

---

## Фаза 4. Оркестрация и API

### 4.1. `src/core/pipeline.py`
- [ ] Класс `Pipeline(detector, reviewer)` с методом `async def run(repo_url, task_file) -> ReviewResponse`:
  1. **Парсинг условия (1 раз)** — общая функция парсинга → `TaskCriteria`.
  2. **Клонирование (1 раз)** — `clone_repo(repo_url)` → `repo_path` (без автоудаления).
  3. **`asyncio.gather()`** только финальных оценок: `detector.analyze_from_path(task_criteria, repo_path)` ∥ `reviewer.evaluate_from_path(task_criteria, repo_path)`.
  4. **Очистка в `finally`**: `shutil.rmtree(repo_path.parent)` строго после завершения gather (успех, исключение, отмена). При сбое одной из задач — отменить вторую и дождаться её (`return_exceptions=True`), по аналогии с текущей логикой `AIDetectionService.analyze`.
  5. **Агрегация** результатов в `ReviewResponse`.
- [ ] Структурное логирование: «ровно одно клонирование», «ровно один парсинг», тайминги этапов.

### 4.2. `src/app.py`
- [ ] FastAPI-приложение; `lifespan` создаёт `AIDetectionService` и `GradingEngine` через фабрики клиентов и кладёт `Pipeline` в `app.state`.
- [ ] Эндпоинт `POST /review`: `repo_url: str = Form(...)`, `task_file: UploadFile` (PDF/DOCX/XLSX; валидация типа). `response_model=ReviewResponse` из `common.models`.
- [ ] Обработчики ошибок: недоступный репозиторий → 4xx с понятным сообщением (без токена и temp-пути); сбой LLM → 502/503; прочее → 500.
- [ ] Чтение `UploadFile` во временный файл/`BytesIO`; pdfplumber/python-docx/openpyxl синхронные — обернуть в `asyncio.to_thread`.

### 4.3. `main.py`
- [ ] Починить импорт (`utils.config` → `common.settings`), запуск uvicorn c `src.app:app`, хост/порт/workers из settings. Запуск: `uv run main.py`.

**Критерий готовности фазы:** `/review` возвращает валидный `ReviewResponse`; в логах на один запрос — ровно одно клонирование и один парсинг.

---

## Фаза 5. Тесты и приёмка

- [ ] Обновить существующие unit-тесты под новые импорты (`common.models`, `common.settings`, `common.llm`, `analyze_from_path`).
- [ ] Новые unit-тесты:
  - [ ] `Pipeline.run`: мок detector/reviewer; clone_repo и парсинг вызываются **ровно один раз**; temp-каталог удалён.
  - [ ] Регресс очистки: искусственное исключение в одной из задач gather → temp-каталог удалён, вторая задача отменена, исключение проброшено (по мотивам `tests/integration/test_cancellation_regression.py`).
  - [ ] `common.llm`: retry на 429/таймаутах, fallback по `model_chain`, валидация structured output.
  - [ ] `app.py`: happy-path `/review` (httpx + заглушки сервисов), 4xx при недоступном репозитории, валидация типа файла.
- [ ] Интеграционный smoke: запуск приложения, `/review` на публичном репозитории с мини-ТЗ, проверка схемы ответа.
- [ ] `ruff check`, `pytest` (порог покрытия ≥ 30% сохраняется).

## Definition of Done (трассировка ТЗ §8)

| Критерий ТЗ | Покрывается |
|---|---|
| `uv run main.py` без ошибок импорта | 4.3 |
| `POST /review` → валидный `ReviewResponse` | 1.2, 4.2, 5 |
| Ровно одно клонирование и один парсинг на запрос | 2.1, 2.2, 4.1, 5 |
| Гарантированное удаление temp-директории после gather (в т.ч. при исключении) | 4.1, 5 |
| Нет дублирующихся Pydantic-моделей в модулях | 1.2, 3.1, 3.2 |
| Промпты в `src/common/prompts.py` | 1.3 |

## Порядок PR (рекомендация)

1. PR: Фаза 1 (common: settings, models, prompts, clients, llm) — с обратной совместимостью через re-export.
2. PR: Фаза 2 + 3 (вынесение I/O, адаптация модулей) — основной рефакторинг.
3. PR: Фаза 4 + 5 (pipeline, app, main, тесты) — сборка и приёмка.
