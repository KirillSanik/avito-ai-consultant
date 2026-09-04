# ai-detector — Homework AI Detector

Асинхронный Python-модуль детекции AI-генерации кода в репозиториях с решениями домашних заданий.

Модуль принимает текст критериев задания и URL репозитория с решением: скачивает репозиторий
локально через `git`, **параллельно** извлекает полную историю коммитов и весь исходный код
(без усечения), передаёт их в локальную LLM через OpenAI-совместимый API со Structured Output и
возвращает валидированный вердикт «Светофор» — `AIAssessmentResult`:

- `status` — `green` (человек) / `yellow` (смешанный/подозрительный) / `red` (явный ИИ/копипаст);
- `confidence` — уверенность модели, `0.0…1.0`;
- `reasoning` — аргументированное обоснование на русском языке;
- `ai_indicators` / `human_indicators` — списки признаков AI- и человеческой генерации.

Поле `task_compliance_score` в схеме намеренно **отсутствует** (оценка соответствия кода критериям
вердиктом не выносится).

## Prerequisites

| Зависимость | Требование | Зачем |
|-------------|------------|-------|
| Python | ≥ 3.10 | `requires-python` в `pyproject.toml` |
| `uv` | последняя стабильная | управление окружением и зависимостями |
| `git` CLI | установлен и доступен в PATH | клонирование и извлечение метаданных (без GitHub API) |
| LLM-сервер | локальный, OpenAI-совместимый API со Structured Output (vLLM/Triton) | оценка; `temperature=0`, strict JSON |

## Установка

```bash
uv sync
```

Создаст `.venv` по `pyproject.toml` и зафиксированным `uv.lock`.

## Использование

```python
import asyncio
from openai import AsyncOpenAI

from ai_detector import AIDetectionService, AIDetectionError


async def main() -> None:
    client = AsyncOpenAI(base_url="http://127.0.0.1:8000/v1", api_key="not-set")
    service = AIDetectionService(client)
    try:
        result = await service.analyze(
            task_criteria="Реализовать LRU-кэш, O(1) get/put, не использовать OrderedDict",
            repo_url="https://github.com/student/lru-hw.git",
        )
    except AIDetectionError as exc:
        print(f"Ошибка анализа: {exc}")
        raise
    print(result.status, result.confidence)
    print(result.reasoning)
    print(result.ai_indicators, result.human_indicators)


asyncio.run(main())
```

Конструктор `AIDetectionService(llm_client)` — чистая сборка подсистем (без I/O и без чтения
окружения). Временная копия репозитория удаляется гарантированно после завершения анализа —
успешного или с ошибкой.

### Переменные окружения

| Переменная | Обязательна | Действие |
|------------|------------|----------|
| `GITHUB_TOKEN` | только для приватных репозиториев | подставляется в URL клонирования как `x-access-token`; в логи и ошибки не попадает |
| `AI_DETECTOR_GIT_TOKEN` | нет | переопределение токена; имеет приоритет над `GITHUB_TOKEN` |
| `AI_DETECTOR_LLM_MODEL` | нет (дефолт — константа пакета) | имя модели для LLM-запросов |

`base_url` и `api_key` LLM — аргументы `AsyncOpenAI` со стороны вызывающего; модуль их не читает.

### Ошибки

Наружу пробрасывается только иерархия `AIDetectionError` (частичных/«мусорных» результатов нет):

| Исключение | Когда |
|------------|-------|
| `AIDetectionError` | базовое исключение модуля |
| `RepoCloneError` | git clone завершился ≠ 0 (неверный/несуществующий URL, нет прав, приватный без токена), сетевой сбой, таймаут клонирования (120 с) |
| `MetadataExtractionError` | сбой `git log` / `git ls-files`; строка истории не распарсилась как JSON (fail-loud) |
| `CodeAggregationError` | сбой чтения файлов; **ни одного** поддерживаемого файла в репозитории («no supported source files») |
| `LLMJudgementError` | LLM недоступна после 3 повторов; `parsed is None`; 404 (модель/эндпоинт); context overflow (объём кода превышает вместимость модели — усечение запрещено) |

Сообщения — на русском, человекочитаемые, без токена доступа и без пути к temp-каталогу.
Временные сбои LLM (таймаут, соединение, 429, 5xx) повторяются автоматически до 3 попыток с
экспоненциальным бэкоффом; неисправимые (404, переполнение контекста) — немедленная ошибка.

### Поддерживаемые файлы кода

Собираются файлы с расширениями `.py`, `.go`, `.rs`, `.js`, `.ts`, `.java`, `.cpp`, `.md`;
служебные директории `.git`, `__pycache__`, `venv`, `node_modules`, `.idea`, `.vscode`
исключаются. Содержимое передаётся в LLM **целиком**, без усечения; merge-коммиты исключены
из истории.

## Тесты

```bash
uv run pytest            # unit + integration
uv run pytest tests/unit -v
uv run pytest tests/integration -v
```
