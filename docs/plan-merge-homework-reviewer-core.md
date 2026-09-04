Ниже представлено техническое задание (ТЗ) в формате Markdown, которое структурирует ваши требования к объединению функционала, созданию FastAPI-приложения и оптимизации пайплайна для исключения дублирования операций клонирования и парсинга.

---

# Техническое задание: Единый API-сервис проверки домашних заданий (AI Review + AI Detection)

## 1. Введение
Цель данного ТЗ – описать архитектуру и требования к реализации единого FastAPI-приложения, которое объединяет функционал модулей `ai_detector` и `homework_reviewer`. Ключевое требование – оптимизация пайплайна: парсинг условия задачи и клонирование репозитория должны выполняться **строго один раз**, после чего результаты передаются в оба модуля для параллельной асинхронной обработки, с гарантированной очисткой временных файлов по завершении.

## 2. Целевая структура репозитория
К текущей структуре добавляются модули для API, единой конфигурации и управления пайплайном:

```text
.
├── main.py                     # Точка входа: запуск uvicorn (uv run main.py)
├── .env                        # Переменные окружения (шаблон в .env.example)
├── .env.example
├── src/
│   ├── app/                    # Новый модуль API и пайплайна
│   │   ├── __init__.py
│   │   ├── api.py              # FastAPI приложение, роуты, lifespan
│   │   ├── pipeline.py         # Класс Pipeline, управляющий жизненным циклом
│   │   └── schemas.py          # Pydantic-модели для запросов и ответов API
│   ├── common/                 # Новые единые модули
│   │   ├── __init__.py
│   │   ├── settings.py         # Единая конфигурация (pydantic-settings)
│   │   └── clients.py          # Фабрика единых клиентов (LLM, хранилища)
│   ├── ai_detector/            # Существующий модуль (требует адаптации, см. п. 5)
│   └── homework_reviewer/      # Существующий модуль (используем парсеры и evaluator)
└── storage/                    # Игнорируется в git, для временных файлов и отчетов
```

## 3. Требования к конфигурации и окружению

### 3.1. Переменные окружения (`.env`)
```env
# LLM Конфигурация
LLM_BASE_URL=http://127.0.0.1:8000/v1
LLM_API_KEY=not-set
DETECTOR_MODEL_NAME=qwen2.5-coder-7b-instruct
REVIEWER_MODEL_NAME=openrouter:gpt-4o
OPENROUTER_API_KEY=sk-or-...

# Доступ к репозиториям
GITHUB_TOKEN=ghp_...
AI_DETECTOR_GIT_TOKEN=ghp_... # Опционально, приоритетнее GITHUB_TOKEN

# Приложение
APP_ENV=development
LOG_LEVEL=INFO
```

### 3.2. Единая конфигурация (`src/common/settings.py`)
Использовать `pydantic-settings` для типизированного чтения `.env`:
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    llm_base_url: str
    llm_api_key: str
    detector_model_name: str
    reviewer_model_name: str
    openrouter_api_key: str | None = None
    github_token: str | None = None
    ai_detector_git_token: str | None = None
    app_env: str = "development"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
```

### 3.3. Единые клиенты (`src/common/clients.py`)
Централизованное создание клиентов для избежания дублирования подключений:
```python
from openai import AsyncOpenAI
from .settings import settings

def get_llm_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "dummy"
    )

def get_openrouter_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=settings.openrouter_api_key
    )
```

## 4. Требования к API (`src/app/api.py`)

### 4.1. Эндпоинт `POST /review`
- **Входные данные** (`src/app/schemas.py`):
  - `repo_url`: строка, ссылка на GitHub-репозиторий.
  - `task_file`: файл (UploadFile), условие задачи (PDF, DOCX, XLSX).
- **Выходные данные**: JSON-объект, содержащий:
  - `review_result`: результат покритериальной оценки (из `homework_reviewer`).
  - `ai_detection_result`: вердикт детектора (`green`/`yellow`/`red`, confidence, reasoning).
  - `processing_time_ms`: общее время выполнения.

### 4.2. Управление жизненным циклом (`lifespan`)
При старте приложения в `lifespan` инициализируется и сохраняется в `app.state` экземпляр `Pipeline`:
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .pipeline import Pipeline
from ..common.clients import get_llm_client, get_openrouter_client

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Инициализация зависимостей
    detector_client = get_llm_client()
    reviewer_client = get_openrouter_client()
    
    # Создание экземпляров сервисов (детектор и ревьюер)
    from ..ai_detector.service import AIDetectionService
    from ..homework_reviewer.evaluator.grading_engine import GradingEngine # или аналогичный класс
    
    detector_service = AIDetectionService(detector_client)
    reviewer_service = GradingEngine(reviewer_client)
    
    # Инициализация пайплайна
    app.state.pipeline = Pipeline(
        detector=detector_service,
        reviewer=reviewer_service
    )
    
    yield
    
    # Очистка при завершении (если требуется)
    app.state.pipeline = None

app = FastAPI(lifespan=lifespan)
```

## 5. Требования к Пайплайну (`src/app/pipeline.py`)

Класс `Pipeline` отвечает за оркестрацию, гарантируя **однократное** выполнение тяжелых операций.

### 5.1. Логика работы `Pipeline.run()`
1. **Парсинг условия**: Вызов существующего парсера из `homework_reviewer.parsers.task_parser` для извлечения текста/критериев из `task_file`. Выполняется 1 раз.
2. **Клонирование репозитория**: Использование модифицированного (или нового) менеджера временных директорий, который **не удаляет** репозиторий сразу после выхода из контекста, а возвращает путь к нему (`repo_path`).
3. **Параллельное выполнение**: Запуск `asyncio.gather()` для двух асинхронных задач:
   - `detector.analyze_from_path(task_criteria, repo_path)` *(адаптированный метод)*
   - `reviewer.evaluate_from_path(task_criteria, repo_path)` *(адаптированный метод)*
4. **Очистка**: Гарантированное удаление временной директории с клоном репозитория (через `shutil.rmtree` с обработкой исключений) **только после** завершения обоих задач в `gather` (в блоке `finally`).
5. **Агрегация**: Сбор результатов в единый словарь/Pydantic-модель и возврат.

### 5.2. Примерная реализация
```python
import asyncio
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

class Pipeline:
    def __init__(self, detector: Any, reviewer: Any):
        self.detector = detector
        self.reviewer = reviewer

    async def run(self, repo_url: str, task_file_path: Path) -> dict:
        temp_dir = None
        try:
            # 1. Парсинг условия (1 раз)
            logger.info("Парсинг условия задачи...")
            task_criteria = await self._parse_task(task_file_path)
            
            # 2. Клонирование репозитория (1 раз)
            logger.info("Клонирование репозитория...")
            temp_dir = Path(tempfile.mkdtemp(prefix="hw_review_"))
            await self._clone_repo(repo_url, temp_dir)
            
            # 3. Параллельное выполнение
            logger.info("Запуск параллельной оценки и детекции...")
            detector_task = self.detector.analyze_from_path(task_criteria, temp_dir)
            reviewer_task = self.reviewer.evaluate_from_path(task_criteria, temp_dir)
            
            ai_result, review_result = await asyncio.gather(
                detector_task, 
                reviewer_task,
                return_exceptions=True
            )
            
            # Обработка исключений, если одно из заданий упало
            if isinstance(ai_result, Exception):
                logger.error(f"Ошибка детектора: {ai_result}")
                ai_result = {"status": "error", "reasoning": str(ai_result)}
            if isinstance(review_result, Exception):
                logger.error(f"Ошибка ревьюера: {review_result}")
                review_result = {"status": "error", "reasoning": str(review_result)}

            return {
                "ai_detection": ai_result,
                "homework_review": review_result
            }
            
        finally:
            # 4. Гарантированная очистка (после завершения обоих процессов)
            if temp_dir and temp_dir.exists():
                logger.info(f"Очистка временной директории: {temp_dir}")
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception as e:
                    logger.error(f"Не удалось удалить временную директорию {temp_dir}: {e}")

    async def _parse_task(self, file_path: Path) -> str:
        # Вызов существующего TaskParser из homework_reviewer
        from ..homework_reviewer.parsers.task_parser import TaskParser
        parser = TaskParser()
        return await parser.extract_criteria(file_path)

    async def _clone_repo(self, repo_url: str, target_dir: Path):
        # Вызов логики клонирования без автоматического удаления
        # Можно использовать RepoCloner.clone_to_path(repo_url, target_dir)
        from ..ai_detector.repo_cloner import RepoCloner
        cloner = RepoCloner()
        await cloner.clone_to_path(repo_url, target_dir)
```

## 6. Необходимые адаптации существующих модулей

Чтобы пайплайн работал корректно, текущие модули требуют минимальных, но критичных изменений:

1. **`src/ai_detector/repo_cloner.py`**:
   - Добавить метод `clone_to_path(repo_url: str, target_path: Path) -> None`, который выполняет клонирование в указанную директорию **без** использования `async with` и последующего удаления.
   - Либо модифицировать текущий `clone`, чтобы он принимал флаг `auto_cleanup: bool = True` (по умолчанию `True` для обратной совместимости, но `False` при вызове из `Pipeline`).

2. **`src/ai_detector/service.py` (`AIDetectionService`)**:
   - Добавить метод `analyze_from_path(task_criteria: str, repo_path: Path) -> AIAssessmentResult`.
   - Этот метод должен пропускать этап клонирования и сразу запускать `asyncio.gather` для `GitMetadataExtractor` и `LocalCodeAggregator` на переданном `repo_path`, после чего передавать данные в `LLMJudge`.

3. **`src/homework_reviewer/`**:
   - Убедиться, что `GradingEngine` (или аналогичный фасад) имеет асинхронный метод `evaluate_from_path(task_criteria: str, repo_path: Path)`, который использует существующие парсеры (`submission_parser` для GitHub-ссылок или локальных путей) и `grading_engine`, не пытаясь самостоятельно клонировать репозиторий.

## 7. Точка входа (`main.py`)

Файл в корне репозитория для запуска через `uv run main.py`:

```python
import uvicorn
from src.app.api import app

if __name__ == "__main__":
    uvicorn.run(
        "src.app.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True, # Только для development
        log_level="info"
    )
```

## 8. Критерии приемки (Definition of Done)

- [ ] Приложение запускается командой `uv run main.py` без ошибок.
- [ ] Эндпоинт `POST /review` принимает `repo_url` и файл условия, возвращая валидный JSON с обоими результатами.
- [ ] В логах видно, что клонирование репозитория происходит **один раз** (одно сообщение о начале и конце клонирования на запрос).
- [ ] В логах видно, что парсинг условия задачи происходит **один раз**.
- [ ] Временная директория с клоном репозитория создается перед `gather` и гарантированно удаляется после его завершения (даже при возникновении исключений в одном из модулей).
- [ ] Конфигурация загружается из `.env` через единый класс `Settings`.
- [ ] Клиенты LLM инициализируются централизованно в `clients.py` и переиспользуются.
- [ ] Покрыто тестами (минимум smoke-тест на эндпоинт с моком клонирования и LLM).

---

### Рекомендации по реализации
1. Начните с рефакторинга `RepoCloner`, выделив логику клонирования в отдельный метод без контекстного менеджера удаления. Это ключевой блок для реализации требования "удаляется после того, как они оба отработают".
2. Используйте `pydantic` модели (`src/app/schemas.py`) для строгой типизации ответа API, что упростит интеграцию с фронтендом и гарантированно даст валидный JSON.
3. Для парсинга файла условия используйте уже существующий `TaskParser` из `homework_reviewer`, передавая ему `SpooledTemporaryFile` или сохраненный временно файл из `UploadFile` FastAPI.