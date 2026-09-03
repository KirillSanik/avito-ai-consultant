# Research: Homework AI Detector

**Feature**: 001-homework-ai-detector | **Date**: 2026-09-03
**Context**: ТЗ (docs/architecture.md) и конституция полностью фиксируют стек, поэтому NEEDS CLARIFICATION-задач нет; документ закрывает best-practice-решения по каждому выбранному компоненту. Формат: **Decision / Rationale / Alternatives considered**.

> Примечание: все решения ниже согласованы со статьями §1–§4 [.specify/memory/constitution.md](../../.specify/memory/constitution.md); ни одно не отменяет «полный код без усечения» и «без GitHub API».

## 1. Каркас проекта и управление зависимостями (`uv`)

- **Decision**: src-layout (`src/ai_detector/`), `pyproject.toml` с `[project]` (name `ai-detector`, `requires-python = ">=3.10"`, dependencies: `pydantic>=2`, `openai>=1.40`, `aiofiles`, `tenacity`, `httpx`), dev-группа: `pytest`, `pytest-asyncio`; `[tool.pytest.ini_options]` с `asyncio_mode = "auto"`, `testpaths = ["tests"]`. Зависимости — только через `uv sync`, артефакт — `uv.lock`.
- **Rationale**: `uv` зафиксирован конституцией; src-layout — стандартный рекомендуемый вариант `uv` для пакетов (не попадает в `sys.path` при запуске из корня, исключает импорты «через каталог»); `asyncio_mode="auto"` убирает ручной `@pytest.mark.asyncio` с каждого теста, упрощая покрытие всех public-методов (конституция §4).
- **Alternatives considered**: flat-layout (корень пакета в корне репозитория) — проще, но конфликтует с `uv`-конвенциями для пакетов и опаснее при запуске скриптов; `pip`/`poetry` — запрещены конституцией.

## 2. `RepoCloner`: асинхронный контекстный менеджер и гарантия очистки

- **Decision**: `RepoCloner.clone(repo_url)` — генератор-контекстный менеджер (`@asynccontextmanager`): создаёт `tempfile.TemporaryDirectory`, выполняет `git clone <url> <dir>` через `asyncio.create_subprocess_exec("git", "clone", ...)`, проверяет return code (≠0 → `RepoCloneError` с хвостом stderr), `yield`-ит `Path` к репозиторию; в `finally` — `TemporaryDirectory.cleanup()` **до** выхода, т.е. гарантированно при любом исключении из тела `async with`. Таймаут на клонирование (константа по умолчанию, напр. 120 c) через `asyncio.wait_for` — превышение → `RepoCloneError`.
- **Rationale**: FR-010 требует гарантированной очистки при любом исходе — паттерн `try/yield/finally` в асинхронном генераторе это обеспечивает декларативно; `create_subprocess_exec` не блокирует event loop (ТЗ §4.2).
- **Alternatives considered**: ручное `asyncio.to_thread(tempfile...)` — не нужно, `TemporaryDirectory` создаётся мгновенно и синхронно; очистка по таймеру/сигналам — избыточно и ненадёжно; постоянный кэш клонов — противоречит FR-010 (эфемерность).

## 3. Приватные репозитории: токен из окружения

- **Decision**: токен читается из переменной окружения (имя фиксировать в контракте: `GITHUB_TOKEN`, допустим переопределение через `AI_DETECTOR_GIT_TOKEN`). При наличии токена публичный/приватный URL `https://github.com/<owner>/<repo>.git` трансформируется в `https://x-access-token:<token>@github.com/<owner>/<repo>.git` **внутри процесса** (только для аргумента subprocess). Токен никогда не попадает в лог, в строку ошибки и в результат.
- **Rationale**: FR-011 — токен только из окружения, не из URL/конфига; `x-access-token` — документированный механизм GitHub для HTTPS-клонов без интерактивного промпта; маскирование в логах — стандартная практика.
- **Alternatives considered**: `git -c http.extraheader="Authorization: Bearer …"` — работает, но токен виден в списке процессов/аудиите subprocess; `.netrc`-файл — создаёт постоянный артефакт (против FR-010); интерактивная авторизация — несовместима с бесчеловечным пайплайном.

## 4. Извлечение истории коммитов: `git log` JSON

- **Decision**: команда строго по ТЗ: `git log --pretty=format:'{"hash":"%H","author":"%an","date":"%aI","message":"%s"}' --no-merges`; вывод читается построчно (stderr/stdout через subprocess), каждая строка — `json.loads` → `CommitInfo`. Строка, не распарсившаяся как JSON, → `MetadataExtractionError` с идентификатором строки/хешем (fail-loud). `date` парсится как ISO 8601 с таймзоной.
- **Rationale**: формат закреплён в ТЗ §4.3 (контракт с командой git); `--no-merges` исключает merge-коммиты (FR-003, допущение spec); `%s` — однострочный subject, риск неэкранированных кавычек низок, а fail-loud согласован с FR-013 («чёткая ошибка, а не частичный результат»).
- **Alternatives considered**: NUL-разделённый формат (`%H%x00%an%x00%aI%x00%s`) — устойчивее к экранированию, но отклоняется от закреплённого в ТЗ контракта команды; GitHub API — запрещён конституцией; regex-парсинг git-вывода — против стиля «валидация, а не парсинг текста» (конституция §3 по духу).

## 5. Дерево файлов: `git ls-files`

- **Decision**: `git ls-files` (stdout построчно → список относительных путей) возвращает **полное** дерево файлов HEAD и используется в промпте как «Структура файлов» (FR-007). Отдельно `LocalCodeAggregator` обходит диск через `pathlib.Path.rglob` — `git ls-files` и rglob не смешиваются.
- **Rationale**: ТЗ §4.3 предписывает `git ls-files` для «чистого списка файлов»; ls-files не зависит от фильтров расширений — структура полная (включая README.md, Makefile и т.д.), а отбор поддерживаемого кода — зона ответственности агрегатора.
- **Alternatives considered**: использовать ls-files и для отбора кода (с расширением по пути) — теряет файлы без расширения, но с кодом? Нет — whitelist только по расширению, эквивалентно; всё же разделение обязанностей (SOLID) чище; рекурсия по `git show HEAD:` — избыточно, мы уже на диске.

## 6. Сбор кода: whitelist/blacklist + `aiofiles` + `Semaphore`

- **Decision**: `Path.rglob("*")` по каталогу клона; отбор: расширение ∈ {`.py`, `.go`, `.rs`, `.js`, `.ts`, `.java`, `.cpp`, `.md`} **и** путь не проходит через директории {`.git`, `__pycache__`, `venv`, `node_modules`, `.idea`, `.vscode`}. Чтение — `aiofiles.open(..., encoding="utf-8")` (бинарные/не-UTF8 файлы — пропускаются с warning-логи, т.к. whitelist текстовых расширений делает это редким). Конкурентность — `asyncio.Semaphore(20)` (константа, конфигурируемая). Итог — одна строка: каждый файл оборачивается маркерами `--- FILE: <path> ---` … `--- END FILE ---` (FR-014). Пустой результат (ни одного файла) → `CodeAggregationError("no supported source files")` (edge case spec).
- **Rationale**: ТЗ §4.4 закрывает whitelist/blacklist, aiofiles, Semaphore и формат маркеров дословно; маркеры позволяют LLM атрибутировать фрагменты файлам (FR-014); лимит 20 — баланс скорости и fd-давления.
- **Alternatives considered**: чтение через `to_thread(Path.read_text)` — допустимо, но ТЗ прямо требует `aiofiles`; синхронное последовательное чтение — медленно на широких репозиториях и против параллельной модели; усечение больших файлов — **запрещено** конституцией/FR-004.

## 7. Параллельный сбор метаданных и кода

- **Decision**: в `AIDetectionService.analyze` — `await asyncio.gather(self.metadata_extractor.extract(repo_path), self.code_aggregator.aggregate(repo_path))` **внутри** блока `async with cloner.clone(...)`. Обработка исключений `gather` без `return_exceptions` — первый сбой пробрасывается доменным исключением (FR-013); очистка клона гарантируется контекстным менеджером независимо.
- **Rationale**: FR-006/SC-001 — параллельность обязательна; `gather` — идиоматичный механизм без барьеров (ТЗ §4.6); обе операции I/O-bound → выигрывают от конкуренции event loop.
- **Alternatives considered**: `TaskGroup` (Python 3.11+) — красивее, но `requires-python>=3.10` исключает; последовательный await — против FR-006; отдельные потоки — лишняя сложность, I/O уже асинхронный.

## 8. LLM: Structured Output через `AsyncOpenAI`

- **Decision**: `LLMJudge` держит `AsyncOpenAI(base_url=..., api_key=...)` (конфигурация из окружения/конструктора: `AI_DETECTOR_LLM_BASE_URL`, `AI_DETECTOR_LLM_API_KEY`, `AI_DETECTOR_LLM_MODEL`; ключ по умолчанию `"not-set"` для локальных серверов). Вызов: `client.beta.chat.completions.parse(model=..., messages=[{system}, {user}], response_format=AIAssessmentResult, temperature=0)` → результат — только `response.choices[0].message.parsed` (объект `AIAssessmentResult`). Если `parsed is None` → бросается `LLMJudgementError` (повторяется retry'ем). В raw-текст ответа regex **не** применяется (конституция §3).
- **Rationale**: ТЗ §4.5 и конституция §3 предписывают `beta.chat.completions.parse` + `response_format=PydanticModel`; SDK сериализует pydantic-схему в `json_schema` (strict) — именно это требуют vLLM/Triton для Structured Output; `temperature=0` — поддержка SC-005 (стабильность вердикта).
- **Alternatives considered**: `client.chat.completions.create` + ручной `model_validate_json` — допустим фоллбек, но первичный путь — `parse()` (конституция §3); `function calling` — избыточен, structured output строже; ручная валидация JSON по ключам — против §3.

## 9. Повторы: `tenacity` на LLM-вызов

- **Decision**: `@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception_type((openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError, openai.APIStatusError, LLMJudgementError)), reraise=True)` на async-методе `LLMJudge.evaluate`. Исчерпание попыток → проброс последнего исключения, сервис оборачивает в `LLMJudgementError` с контекстом (FR-012/SC-006). Ошибки **не** повторяться: `openai.NotFoundError` (404 модель/эндпоинт) и ошибки конфигурации — immediate fail.
- **Rationale**: FR-012/SC-006 — 3 автоматических повтора только для временных сбоев; экспоненциальный бэкофф — стандарт; tenacity нативно оборачивает корутины (конституция §3).
- **Alternatives considered**: фиксированная задержка — хуже при перегрузке LLM; больше попыток — растёт latency без выгоды; повторы на все исключения — маскирует устойчивые сбои (нарушает SC-006).

## 10. Превышение вместимости модели (context overflow)

- **Decision**: ошибка от LLM-сервера о превышении контекста (обычно 400 с сообщением про токены/контекст, `openai.BadRequestError`) **не** входит в множество retry'ей — пробрасывается как `LLMJudgementError` с понятным текстом «объём кода превышает вместимость модели; усечение запрещено».
- **Rationale**: FR-004/FR-013 + допущение spec: усечение запрещено, повтор того же запроса не изменит объём.
- **Alternatives considered**: усечение/чанкинг — прямо запрещено; автоматическое переключение на меньшую модель — вне scope v1 и не детерминировано.

## 11. Доменная модель ошибок

- **Decision**: базовое `AIDetectionError(Exception)` → `RepoCloneError`, `MetadataExtractionError`, `CodeAggregationError`, `LLMJudgementError`. Каждый несёт человекочитаемое сообщение (без токенов/путь к temp не обязан, но без служебного шума). `AIDetectionService.analyze` пробрасывает только эту иерархию наружу.
- **Rationale**: FR-013 (чёткие ошибки вместо частичных результатов); типизированные ошибки позволяют вызывающему различать сбой скачивания, сбора и оценки (тестируемость, SOLID).
- **Alternatives considered**: единый `AnalysisError` с кодом — хуже для type hints (конституция §2); возврат `Optional[AIAssessmentResult]` + поле errors — против контракта «валидированный объект или ошибка».

## 12. Детерминированность и язык вывода

- **Decision**: `temperature=0` (§8); в system prompt явно закреплено: обоснование — на русском, ответ строго JSON по схеме, без текста вне JSON (ТЗ §5). Язык списков признаков — русский (FR-008).
- **Rationale**: SC-005 (стабильность) и FR-008 (русское обоснование); промпт ТЗ §5 уже содержит эти инструкции — `prompts.py` воспроизводит их дословно.
- **Alternatives considered**: температура > 0 — вредит SC-005; англоязычный вывод — против FR-008.
