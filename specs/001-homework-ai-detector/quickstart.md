# Quickstart: Homework AI Detector

**Feature**: 001-homework-ai-detector | **Цель**: пошагово проверить фичу end-to-end (установка → unit-тесты → integration → реальный прогон с мок-LLM и с реальным LLM-сервером).
Контракты: [public-api.md](./contracts/public-api.md), [llm-structured-output.md](./contracts/llm-structured-output.md). Схемы данных: [data-model.md](./data-model.md).

## 1. Prerequisites

| Зависимость | Требование | Зачем |
|-------------|------------|-------|
| Python | ≥ 3.10 | `requires-python` в pyproject |
| `uv` | последняя стабильная | управление окружением и зависимостями (конституция §1) |
| `git` CLI | установлен в ОС и в PATH | клонирование и извлечение метаданных (FR-002) |
| LLM-сервер | локальный, OpenAI-совместимый API со Structured Output (vLLM/Triton) | оценка; `temperature=0`, strict JSON |
| `GITHUB_TOKEN` | только для приватных репозиториев | аутентификация клонирования (FR-011) |

Проверка: `python3 --version && uv --version && git --version`.

## 2. Установка

```bash
uv sync            # создаёт .venv по pyproject.toml, фиксирует uv.lock
```

## 3. Unit-тесты (моки subprocess / fs / LLM — конституция §4)

```bash
uv run pytest tests/unit -v
```

**Ожидаемо**: все тесты зелёные. Критические проверяемые поведения (по FR):

- `test_repo_cloner.py`: клон запускается как subprocess; `returncode ≠ 0` → `RepoCloneError`; **temp-каталог удалён при исключении в теле** `async with` (FR-010); токен из окружения подставлен в URL и **отсутствует** в сообщении ошибки (FR-011).
- `test_git_metadata.py`: JSON-история парсится в `list[CommitInfo]`; merge-коммиты отсутствуют (`--no-merges`); невалидная строка JSON → `MetadataExtractionError` (fail-loud); `git ls-files` → полное дерево файлов.
- `test_code_aggregator.py`: whitelist-расширения и blacklist-директории соблюдаются; маркеры `--- FILE: … --- / --- END FILE ---` на месте; контент **полный** (FR-004); параллельные чтения ограничены Semaphore; пустой результат → `CodeAggregationError` (FR-013).
- `test_llm_judge.py`: вызов идёт через `beta.chat.completions.parse` с `response_format=AIAssessmentResult`; временные сбои повторяются ≤3 раз; 404/overflow — без повторов; `parsed is None` → `LLMJudgementError`.
- `test_service.py`: `analyze` собирает метаданные и код **параллельно** (FR-006); очистка клона гарантирована при любом исключении; наружу — только иерархия `AIDetectionError`.

## 4. Integration-дым (сборный пайплайн)

```bash
uv run pytest tests/integration -v
```

Сценарий: фиксатурный репозиторий (локальный `git init`/коммиты в tmp + реальный `git clone` file:// или локальным путём) + **мок `AsyncOpenAI`** → `AIDetectionService.analyze` возвращает полный `AIAssessmentResult`; после вызова temp-каталогов не остаётся (SC-004).

## 5. End-to-end прогон (реальный LLM-сервер)

1. Поднять/проверить LLM-сервер (vLLM/Triton) с моделью, поддерживающей Structured Output; получить `base_url` (например `http://127.0.0.1:8000/v1`).
2. Для приватного репозитория: `export GITHUB_TOKEN=<токен>`.
3. Скрипт прогона (минимальный, полный контракт — в public-api.md §5):

```bash
uv run python - <<'PY'
import asyncio
from openai import AsyncOpenAI
from ai_detector import AIDetectionService, AIDetectionError

async def main() -> None:
    service = AIDetectionService(AsyncOpenAI(base_url="http://127.0.0.1:8000/v1", api_key="not-set"))
    try:
        r = await service.analyze(
            task_criteria="Текст критериев домашнего задания",
            repo_url="https://github.com/<owner>/<repo>.git",
        )
    except AIDetectionError as exc:
        raise SystemExit(f"Ошибка анализа: {exc}")
    print(r.model_dump_json(indent=2))

asyncio.run(main())
PY
```

**Ожидаемый результат** (по SC/FR):
- JSON с ровно пятью полями: `status` ∈ {green, yellow, red}, `confidence` ∈ [0,1], `reasoning` (русский, не пустое), `ai_indicators`[], `human_indicators[]` (SC-002, FR-008); поля `task_compliance_score` нет (FR-009).
- Время прогона для репозитория ≤20 поддерживаемых файлов — < 5 минут (SC-001); сбор метаданных и кода идёт параллельно (FR-006).
- В каталогах временных файлов (tmp) после прогона — следов клона не остаётся, включая повторный прогон после принудительного срыва (SC-004).
- Повторный прогон на том же неизменённом репозитории даёт тот же `status` (SC-005).

## 6. Сценарии негативной проверки (ручная верификация FR-013)

| Сценарий | Команда/действие | Ожидаемо |
|----------|------------------|----------|
| Несуществующий URL | `repo_url="https://github.com/none/nope.git"` | `RepoCloneError` с русским сообщением, без следов temp |
| Приватный без токена | unset `GITHUB_TOKEN`, приватный URL | `RepoCloneError` о правах/недоступности |
| Репозиторий без кода (только изображения) | URL с таким репо | `CodeAggregationError`: «no supported source files» |
| Ложный `base_url` LLM | мёртвый порт | `LLMJudgementError` после 3 повторов (SC-006), без «мусорного» вердикта |
| Огромный репозиторий | объём кода > контекста модели | `LLMJudgementError` про вместимость; **усечения кода не происходит** (FR-004) |

## 7. Критерий «готово» (связка с Definition of Done ТЗ)

- [ ] `uv sync && uv run pytest -v` — весь набор зелёный (unit + integration).
- [ ] End-to-end прогон §5 возвращает валидный `AIAssessmentResult` по реальному публичному репозиторию.
- [ ] Все пункты негативной таблицы §6 дают ожидаемые исключения и чистые temp-каталоги.
- [ ] В схеме нет `task_compliance_score`; в промпте — полный код (проверить логом/мок-захватом запроса LLM).
