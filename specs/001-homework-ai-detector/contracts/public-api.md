# Contract: Public API — `ai_detector`

**Feature**: 001-homework-ai-detector | **Type**: библиотека (программный API)
Конституция: SOLID, строгие type hints (PEP 484), `Any` запрещён без обоснования.

## 1. Публичный экспорт (`ai_detector/__init__.py`)

```python
from ai_detector.service import AIDetectionService
from ai_detector.models import AIAssessmentResult, CommitInfo
from ai_detector.exceptions import (
    AIDetectionError,
    RepoCloneError,
    MetadataExtractionError,
    CodeAggregationError,
    LLMJudgementError,
)
```

Всё, что не экспортировано здесь, считается внутренним и может меняться без предупреждения.

## 2. `AIDetectionService` (единственная точка входа, фасад)

### Конструктор

```python
class AIDetectionService:
    def __init__(self, llm_client: AsyncOpenAI) -> None: ...
```

- `llm_client` — клиент, указанный вызывающим на локальный LLM-сервер:
  `AsyncOpenAI(base_url=<LLM_BASE_URL>, api_key=<LLM_API_KEY>)` (модель задаётся в вызовах `LLMJudge`).
- Конструктор **не** выполняет I/O, не читает окружение — чистая сборка подсистем (SRP, тестируемость DI):
  внутри создаются `RepoCloner`, `GitMetadataExtractor`, `LocalCodeAggregator`, `LLMJudge(llm_client)`.

### Основной метод

```python
async def analyze(self, task_criteria: str, repo_url: str) -> AIAssessmentResult: ...
```

| Параметр | Тип | Контракт |
|----------|-----|----------|
| `task_criteria` | `str` | непустой текст критериев задания (PDF-парсинг не требуется, spec-допущение) |
| `repo_url` | `str` | URL репозитория, доступный по `git clone` (https; приватные — с токеном из окружения) |

**Возврат**: валидированный `AIAssessmentResult` (см. data-model.md, сущность 4) либо исключение из иерархии §3. Частичных результатов нет.

**Гарантии поведения** (контрактные):
1. **Полнота данных**: в LLM уходит полный код всех поддерживаемых файлов без усечения (FR-004); merge-коммиты исключены из истории (FR-003).
2. **Параллельность**: сбор метаданных и кода — параллельно (FR-006).
3. **Очистка**: временная копия репозитория удаляется всегда, включая исключения и отмены (FR-010, SC-004).
4. **Повторы LLM**: только временные сбои повторяются (3 попытки, экспоненциальный бэкофф); устойчивые — немедленная ошибка (FR-012, SC-006).
5. **Типизация**: сигнатуры полностью типизированы; `Any` отсутствует.

## 3. Ошибки (контракт исключений)

| Исключение | Когда | Содержимое сообщения |
|------------|-------|----------------------|
| `RepoCloneError` | git clone завершился ≠0 (неверный URL, не существует, нет прав, приватный без токена), сетевой сбой, таймаут клонирования | причина на русском + хвост stderr git (без токена) |
| `MetadataExtractionError` | сбой `git log`/`git ls-files`; строка истории не распарсилась как JSON (fail-loud) | идентификатор строки/контекста |
| `CodeAggregationError` | сбой чтения файлов; **ни одного** поддерживаемого файла в репозитории | «no supported source files» для edge case |
| `LLMJudgementError` | LLM недоступна после 3 повторов; `parsed is None`; context overflow (объём кода > вместимости модели, усечение запрещено); 404 модель/эндпоинт | причина + «повторы исчерпаны» где уместно |

Общее правило: сообщения — на русском, человекочитаемые, **без** токена доступа и без пути к temp-каталогу в обязательной части.

## 4. Переменные окружения (влияющие на API)

| Переменная | Обязательна | Действие |
|------------|------------|----------|
| `GITHUB_TOKEN` (или переопределение `AI_DETECTOR_GIT_TOKEN`) | только для приватных репозиториев | подставляется в URL клонирования как `x-access-token` (research §3); в логи/ошибки не попадает |
| `AI_DETECTOR_LLM_MODEL` | нет (дефолт — константа пакета) | имя модели для `LLMJudge` |

`base_url`/`api_key` LLM — аргументы `AsyncOpenAI` со стороны вызывающего (DI), окружение не читается.

## 5. Пример использования (контрактный)

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

## 6. Нон-контрактные заметки

- **Без состояния**: вызовы `analyze` независимы; повторный анализ того же репозитория детерминирован по статусу (SC-005, `temperature=0`).
- **Один репозиторий за вызов**; batch — вне scope v1 (spec-допущение).
- **Вердикт — поддержка решения преподавателя**, не окончательное юридическое заключение (spec-допущение).
