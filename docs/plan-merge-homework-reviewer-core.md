# План объединения веток: `ai-detector` (текущая) + `feature/homework-reviewer-core`

**Статус:** утверждён (решения от 2026-07, см. ниже), исполняется.
**Цель:** один репозиторий авито-AI-консультанта с двумя фиче-пакетами (`ai_detector`,
`homework_reviewer`) и общим слоем `common`, без дублирования логики (конституция v1.1.0, принцип IV — DRY).

**Утверждённые решения:**
1. Старые ветки (`ai-detector`, `feature/homework-reviewer-core`, `main`) **не трогаем**;
   результат — только новая ветка `integrate/homework-reviewer-core` (от `ai-detector`),
   мерж обратно в `ai-detector` не выполняется.
2. Имя проекта в `pyproject.toml` — **`avito-ai-consultant`** (`ai-detector` — это имя
   ветки, не проекта).
3. `data/` — выносим из git-индекса и в `.gitignore` (файлы остаются локально).
4. `main` — не трогаем до отдельного решения.

---

## 1. Снимок состояния веток

Ветки **не имеют общего предка** (`git merge-base` пуст) — это две независимые линии
разработки одного продукта:

| | `ai-detector` (текущая, HEAD `76e123a`) | `feature/homework-reviewer-core` (`54d9796`) |
|---|---|---|
| Назначение | Детекция AI-генерации кода в репозитории (async-библиотека) | 3-этапный ревьюер ДЗ: PDF задания → парсинг сдачи → покритериальная оценка + PDF-отчёт (click-CLI) |
| Кода | `src/ai_detector/` (~1 300 строк), публичный API через `__init__` | `src/*` (~2 900 строк), плоский пакет, импорты `from src.` |
| LLM | `AsyncOpenAI` + `beta.chat.completions.parse` (Structured Output), tenacity, 1 модель из env | `instructor` (JSON-режим, синхронный), ручные retry + фолбэк по цепочке free-моделей OpenRouter |
| Git-клон | `RepoCloner`: hardened `spawn_git` (cancel-safe), `x-access-token`, маскирование секрета, таймаут 120 с | inline `subprocess.run(["git","clone","--depth","1"])`, токен как user в URL, без таймаута |
| Конфиг | env-переменные читаются точечно в `LLMJudge` / `RepoCloner` | `AppConfig` (dataclass) + `load_dotenv`, провайдеры openrouter/ollama |
| Тесты | 9 test-файлов, pytest + pytest-asyncio + cov gate 30% | отсутствуют |
| Упаковка | pyproject (hatchling, uv), ruff, mypy, `uv.lock` | `requirements.txt`, без lint/тестов |
| Мусор в ветке | — | `data/` (бинарники 716K + `*:Zone.Identifier`), `storage/` (JSON-состояние 252K, при этом в .gitignore), `requirements.txt`, `main.py` |
| Документация | specs/001, specs/002, docs/architecture.md, constitution v1.1.0, .specify | PRODUCT_01..03, PROJECT_DESCRIPTION_INTERIM, copilot-instructions.md |

Обе ветки уже разошлись на `origin`; локальная `ai-detector` опережает `origin/ai-detector` на 2 коммита.

---

## 2. Карта дублирующейся логики

| # | Логика | `ai-detector` | `homework-reviewer-core` | Решение |
|---|--------|---------------|--------------------------|---------|
| 1 | Клонирование GitHub-репозитория (temp-dir, токен, ошибки) | `repo_cloner.py` + `_spawn.py` (сильная версия) | `submission_parser.parse_github_repository` (слабая копия) | **Одна реализация** — переносим `RepoCloner` в `common/git/`; reviewer использует его через sync-обёртку |
| 2 | Классификация ошибок LLM (retryable / unavailable) | `llm_judge.py`: `APITimeoutError/RateLimitError/5xx` — retry, `404/context` — fatal | `grading_engine._is_retryable_error/_is_model_unavailable`: обход цепочки исключений + message-маркеры | **Единый модуль** `common/llm/resilience.py` (суперпозиция обеих эвристик) |
| 3 | Повторы LLM-запроса | tenacity (3 попытки, exp backoff) | ручной цикл `for attempt` + `sleep` | **Один механизм** — tenacity (конституция §III); модельный фолбэк-цепочка — общий helper |
| 4 | Выбор файлов репозитория (extension-списки, excluded dirs, лимиты) | `code_aggregator._collect_files` (os.walk с прунингом) | `submission_parser._repository_files` (rglob + пост-фильтр, 1MB, excluded names) | **Единая** `common/git/files.py`: `RepoFilePolicy` + `select_files()`; списки — константы фич |
| 5 | Извлечение текста из PDF (pdfplumber: текст/таблицы/ссылки/картинки) | — | `task_parser.extract_pdf_content` **и** `submission_parser._parse_pdf` (две копии pdfplumber-цикла) | **Одна** `common/documents/pdf.py: extract_pdf() -> PdfContent` |
| 6 | Таблица → Markdown | — | `task_parser._table_to_markdown` (+ странная function `self_row`) | `common/documents/tables.py: table_to_markdown()` |
| 7 | JSON-хранилища (save/load + валидация id) | — | `task_repository.py`, `submission_repository.py`, `evaluation_repository.py` — **покап-копия ×3** | `common/storage/json_repository.py: JsonRepository[T]` + три тонких наследника |
| 8 | Конфиг/env (provider, model, API key, git token, test-mode лимиты) | env точечно в двух классах | `AppConfig` | **Один** `common/config.py` (единый источник имён env и провайдер-логики) |
| 9 | Проектные метаданные | pyproject, .gitignore, README, uv.lock | requirements.txt, .gitignore, README, .env.example | Одиночные файлы: pyproject (uv), .gitignore, README, .env.example |

**Не дублируется (остаётся в своей фиче):** `git_metadata.py` + `CommitInfo` + `format_commit_history`
(только detector), парсеры docx/xlsx/links + модели рубрики/оценки + PDF-отчёт + промпты оценки
(только reviewer), `AIAssessmentResult` + промпты детектора (только detector). Промпты **не**
объединяем — это разные тексты, объединять смысл нечего.

---

## 3. Целевая архитектура

```
pyproject.toml            # единый: hatchling (3 пакета), uv, ruff, pytest; [project.scripts]
.env.example              # единый: OPENROUTER_API_KEY, GITHUB_TOKEN, AI_DETECTOR_GIT_TOKEN, AI_DETECTOR_LLM_MODEL
README.md                 # проект уровня; пофичевые README → docs/
docs/
  architecture.md         # ТЗ + обновлённый раздел о common-слое
  ai-detector.md          # содержимое бывшего README ai-detector
  product/                # PRODUCT_01..03, PROJECT_DESCRIPTION_INTERIM, copilot-instructions (из reviewer)
specs/                    # 001, 002 (как есть); 003 для reviewer — отдельная итерация (out of scope)
src/
  common/
    config.py             # AppSettings (из AppConfig) + git_token() + llm_model() + OPENROUTER_FREE_MODELS
    git/
      spawn.py            # из ai_detector/_spawn.py (без изменений)
      cloner.py           # из ai_detector/repo_cloner.py + параметр depth: int | None
      files.py            # RepoFilePolicy + select_files()
    documents/
      pdf.py              # extract_pdf() -> PdfContent(text, tables, links, image_count)
      tables.py           # table_to_markdown(), format_markdown_row()
    storage/
      json_repository.py  # JsonRepository[T: BaseModel] (save/load/валидация id)
    llm/
      client.py           # provider → OpenAI / AsyncOpenAI / instructor-клиент
      resilience.py       # is_transient(), is_model_unavailable(), ModelChain + fallback-helper
  ai_detector/            # ПУБЛИЧНЫЙ API БЕ ИЗМЕНЕНИЙ (__init__ тот же)
    service.py, llm_judge.py, git_metadata.py, code_aggregator.py, utils/
    # _spawn.py и repo_cloner.py переезжают в common/git (внутренние, не экспортируются)
  homework_reviewer/      # из src/* reviewer-ветки, импорты переписаны
    cli.py                # из main.py; entry point `homework-reviewer`
    task_parser.py, submission_parser.py, docx_parser.py, xlsx_parser.py, link_parser.py
    grading_engine.py, pdf_generator.py
    repositories.py       # TaskRepository/SubmissionRepository/EvaluationRepository — наследники JsonRepository
    models/               # rubric.py, submission.py, evaluation.py (как есть)
tests/
  unit/, integration/     # тесты detector (импорты обновлены)
  test_common_*.py        # новые: cloner (токен/маскирование), files, pdf, tables, json_repository, resilience
  test_reviewer_*.py      # новые: парсеры (фикстуры), fallback-regex рубрики, grading_engine с mock-клиентом, CLI smoke
```

Принципиальные решения:

1. **`common` — только кросс-фичевая логика.** Фичевые модели, промпты, парсеры docx/xlsx,
   PDF-отчёт в common не переезжают.
2. **Асинхронность не навязываем.** `common/git/cloner.py` остаётся async (это лучшая
   реализация); для sync-CLI reviewer — обёртка `clone_sync()` на `asyncio.run`.
   `LLMJudge` (async/parse) и `GradingEngine` (sync/instructor) **не сливаем** — разные
   контракты; объединяем только клиент-фабрику, resilience и retry-политику.
3. **Публичный API `ai_detector` не меняется** — реэкспорт `__init__.py` остаётся тем же;
   двигаются только внутренние модули.
4. **Конституция** — v1.2.0: область применения расширяется на оба фиче-пакета; §II
   дополняется допущением instructor/JSON-режима для облачного провайдера (локальный
   провайдер — только Structured Output); добавляется принцип «кросс-фичевая логика живёт
   только в `common`» (жёсткое DRY). Внести через `speckit-constitution`.

---

## 4. Поэтапное объединение

Каждый коммит — зелёное дерево (`uv run pytest` + `uv run ruff check`).

### Фаза 0 — подготовка (0.5 ч)
```bash
git switch -c integrate/homework-reviewer-core   # от ai-detector (текущая)
```
Опционально: `git push origin ai-detector` (2 локальных коммита не опубликованы).

### Фаза 1 — импорт reviewer-ветки (1 коммит)
```bash
git merge origin/feature/homework-reviewer-core --allow-unrelated-histories \
    -m "merge: import feature/homework-reviewer-core (unrelated histories)"
```
Конфликтов ровно два: `README.md` и `.gitignore` (решаем временно в пользу `ai-detector`;
полная сшивка — в фазе 2). Остальное — чистое добавление.
*Альтернатива (если важна чистота истории без бинарников): не merge, а чистый импорт
`git archive origin/feature/homework-reviewer-core | tar -x` + выборочный commit —
линия reviewer в DAG не сохранится. Рекомендую merge: репо маленькое, дженезис прослеживаем.*

### Фаза 2 — реорганизация и упаковка (1 коммит, механический)
- `git mv` reviewer-модулей: `src/{config,models,parsers,evaluator,reports,repository}` →
  `src/homework_reviewer/`; `main.py` → `src/homework_reviewer/cli.py`; удалить
  `src/__init__.py` (reviewer) — `src/` остаётся namespace-каталогом.
- Переписать импорты: `from src.x` → `from homework_reviewer.x` (в т.ч. внутри пакета,
  `evaluator/__init__.py` использует абсолютный `src.`-импорт — исправить).
- **Гигиена трекинга:** `git rm -r --cached data storage` (файлы остаются локально),
  `git rm requirements.txt`; в `.gitignore` добавить `data/`, `storage/`, `*:Zone.Identifier`
  (объединённый .gitignore: шаблон detector + строки reviewer).
- `pyproject.toml`: `name = "avito-ai-consultant"`; hatchling
  `packages = ["src/ai_detector", "src/homework_reviewer", "src/common"]` (common создаётся
  в фазе 3, в фазе 2 — два пакета); `[project.scripts] homework-reviewer = "homework_reviewer.cli:cli"`.
- Зависимости (`uv add`): `instructor>=1.0`, `click>=8.0`, `requests>=2.31`,
  `beautifulsoup4>=4.12`, `python-docx>=1.0`, `openpyxl>=3.1`, `pdfplumber>=0.10`,
  `python-dotenv>=1.0`, `reportlab>=4.0`; `httpx` → в dev-group (используется только в тестах);
  `PyMuPDF` не добавляем (в requirements.txt было, но в коде не используется).
- README.md — сшить (детальный блок detector выносится в `docs/ai-detector.md`);
  PRODUCT_*/PROJECT_DESCRIPTION/copilot-instructions → `docs/product/`.
- `cli.py`: убрать `update_documentation_status()` (мутация README при каждом запуске —
  артефакт PoC; в сшитом README маркер не будет).
- ruff: `known-first-party += ["homework_reviewer"]` (позже + `"common"`).

### Фаза 3 — вынос common-слоя (6 коммитов, по одному компоненту)
1. **3a `common/config.py`** — `AppSettings` (фактически `AppConfig` + env-имена detector:
   `AI_DETECTOR_LLM_MODEL`, `AI_DETECTOR_GIT_TOKEN`/`GITHUB_TOKEN`); `LLMJudge` и `RepoCloner`
   читают env только через этот модуль. `OPENROUTER_FREE_MODELS` — в `common/llm`.
2. **3b `common/git/{spawn,cloner}.py`** — перенос `ai_detector/_spawn.py`,
   `ai_detector/repo_cloner.py`; в `RepoCloner.clone` добавить `depth: int | None = None`
   (reviewer клонирует с `--depth 1`, detector — как раньше). Инжекция токена — только
   `x-access-token` (вариант «токен как user в URL» из reviewer убираем). Для reviewer —
   `clone_sync()`. `ai_detector` импортирует из `common.git`; `submission_parser` теряет
   собственный `subprocess.run` + `_authenticated_clone_url`.
3. **3c `common/git/files.py`** — `RepoFilePolicy` + `select_files()` (os.walk-прунинг
   detector как эталон); политики: `CODE_REPOSITORY_POLICY` (detector) и
   `SUBMISSION_REPOSITORY_POLICY` (reviewer: свои списки расширений, 1MB, excluded names).
   `LocalCodeAggregator._collect_files` и `SubmissionParser._repository_files` становятся
   вызовами `select_files` + фичевые чтения (async aiofiles / sync read_text).
4. **3d `common/documents/{pdf,tables}.py`** — `extract_pdf()` (один проход pdfplumber:
   текст с `## Страница N`, таблицы в строках **и** markdown, ссылки из annots, image_count);
   `task_parser` строит `full_instructions` из `text + tables_markdown` (поведение как было),
   `submission_parser` использует `text/tables/links/image_count`. `self_row` →
   `format_markdown_row` (публичное имя, без префикса-опечатки).
5. **3e `common/storage/json_repository.py`** — generic `JsonRepository[T]` (id-валидация,
   save/load, storage_dir); `homework_reviewer/repositories.py` — три класса по ~6 строк.
6. **3f `common/llm/{client,resilience}.py`** — фабрика клиентов (sync `OpenAI`/instructor,
   async `AsyncOpenAI`), единая классификация ошибок (суперпозиция эвристик: status-коды
   {402,429,≥500,таймауты,соединения,IncompleteOutput/InstructorRetry} + message-маркеры
   OpenRouter `in_flight_budget_exhausted/rate limit`; unavailable: 404), `ModelChain` +
   fallback-helper. `LLMJudge`: tenacity остаётся, классификация — из common (поведение 1:1).
   `GradingEngine`: ручной цикл retry → tenacity с той же политикой + внешний
   модельный фолбэк через common; `evaluator/client_factory.py` удаляется (фабрика — в common).
   `click.echo` в движках → `logging` (CLI логирует, как detector).

### Фаза 4 — тесты (1–2 коммита)
- Обновить импорты в `tests/unit/test_repo_cloner.py`, `tests/integration/test_cancellation_regression.py`
  (`ai_detector._spawn/repo_cloner` → `common.git.*`); остальная батарея detector не трогается.
- Новые: `test_common_git.py` (инжекция/маскирование токена, таймаут, depth, политика
  `select_files`), `test_common_documents.py` (фикстурные PDF), `test_json_repository.py`,
  `test_resilience.py` (классификация по цепочкам исключений), `test_reviewer_parsers.py`
  (xlsx/docx/PDF-фикстуры из `data/`), `test_task_parser_fallback.py` (regex-критерии без LLM),
  `test_grading_engine.py` (mock instructor-клиента: retry, фолбэк модели, клампинг баллов),
  CLI smoke через `click.testing.CliRunner`.
- **Риск:** `--cov=src` покрывает все три пакета; reviewer без тестов тянет покрытие вниз
  (<30%). Митигация — тесты выше; если gate всё ещё красит, решение: либо дополнить тесты,
  либо сузить `source` до `["src/ai_detector", "src/common"]` (явно обосновать в коммите —
  constitution требует DRY, но не запрещает поэтапное покрытие).

### Фаза 5 — документация и constitution (1 коммит)
- Constitution **v1.2.0** (через `speckit-constitution`): scope → «Avito AI Consultant
  (detector + reviewer)»; §II LLM-правила с допущением instructor для облачного провайдера;
  новый принцип: кросс-фичевая логика — только в `common`.
- `docs/architecture.md` — схема common-слоя и правила размещения (что куда).
- README — единая таблица env-переменных, quickstart двух модулей, CLI-команды reviewer.

### Фаза 6 — финиш
- Итог — новая ветка `integrate/homework-reviewer-core`; `ai-detector`, `feature/homework-reviewer-core`
  и `main` **не изменяются** (решение 1 и 4).
- Публикация новой ветки в origin — по требованию пользователя (по умолчанию не пушим).
- `origin/kirillsanik-frontend` — out of scope.

**Итог: ~10–12 коммитов, каждый зелёный.**

---

## 5. Риски и решения по ним

| Риск | Влияние | Митигация |
|------|---------|-----------|
| Покрытие 30% на весь `src` при нетестированном reviewer | Красный gate | Тесты фазы 4; при необходимости сузить `source` (с обоснованием) |
| Разные LLM-контракты (parse vs instructor) | Тенденция к «слиянию в кучу» | Объединяем только resilience/фабрику/цепочку; адаптеры остаются у фич |
| Синхронный CLI поверх async-клонирования | `asyncio.run` в CLI | Допустимо (CLI, своего event loop нет); `clone_sync` — единственная точка |
| Hatchling multi-package + переименование проекта | `uv sync`/lock | `uv add`/`uv lock` обновят; проверить install в чистом venv |
| Мусор reviewer (бинарники, Zone.Identifier, storage) в истории после merge | +~1 МБ истории | `git rm --cached` в фазе 2; репо маленькое — rewrite не нужен |
| Конфликт конституции (§II — только AsyncOpenAI parse) | Ревью-блокировка | Явное поправка v1.2.0 ДО фазы 3f |
| `instructor` × `openai` версии | Совместимость | uv разрешит; пин `instructor>=1.0` + смоук-тест фабрики |

## 6. Критерии готовности (DoD)

1. `uv sync && uv run pytest` — зелёно, coverage ≥ 30%; `uv run ruff check src tests` — чисто.
2. `uv run homework-reviewer --help` — CLI доступна как entry point.
3. Публичный API `ai_detector` без изменений: существующие тесты integration/proxy-поведения
   проходят без правок логики.
4. Ни один алгоритм (клон, retry, PDF, выбор файлов, JSON-хранилище, конфиг) не представлен
   в двух местах (проверка: `grep` дублей + код-ревью по принципу IV).
5. В `data/` и `storage/` в git-индексе нет ни одного файла; `README.md`, `.gitignore`,
   `pyproject.toml`, `.env.example` — по одному.
6. `git log --oneline` новой линии содержит merge-коммит с линией reviewer (прослеживаемость).
