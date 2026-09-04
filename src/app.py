"""FastAPI-приложение: единый эндпоинт ``POST /review`` (ТЗ §4).

``lifespan`` собирает сервисы из фабрик ``common.clients`` и кладёт
``Pipeline`` в ``app.state``. Эндпоинт принимает ``repo_url`` (Form) и
``task_file`` (UploadFile: PDF/DOCX/XLSX), пишет файл во временный каталог
(синхронная запись — в отдельном потоке) и возвращает ``ReviewResponse``
из ``common.models``.

Кодирования ошибок (ТЗ §4.2):
- недоступный репозиторий / неподдерживаемый файл — 422 с понятным сообщением
  (без токена и temp-пути — маскирует ``core.repo_clone``);
- сбой LLM (детектор/ревьюер/разбор условия) — 502;
- прочее — 500 (стандартное поведение FastAPI).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from ai_detector.service import AIDetectionService
from ai_detector.utils.exceptions import LLMJudgementError, RepoCloneError
from common.clients import get_llm_client, get_openrouter_client
from common.llm import LLMError
from common.models import ReviewResponse
from common.parsers import SUPPORTED_TASK_EXTENSIONS
from common.parsers.exceptions import TaskParseError
from common.settings import get_settings
from core.pipeline import Pipeline
from homework_reviewer.evaluator.grading_engine import GradingEngine
from homework_reviewer.exceptions import EvaluationError

logger = logging.getLogger(__name__)

#: Префикс temp-каталога загруженных условий (тот же стиль, что у ``core.repo_clone.TEMP_DIR_PREFIX``).
TASK_FILE_PREFIX = "avito-review-task-"


def _error_response(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Старт: сборка Pipeline из фабрик клиентов; стоп: сброс состояния."""
    settings = get_settings()
    detector_service = AIDetectionService(get_llm_client(settings))
    reviewer_service = GradingEngine(get_openrouter_client(settings), settings)
    app.state.pipeline = Pipeline(
        detector=detector_service,
        reviewer=reviewer_service,
        settings=settings,
    )
    logger.info("Pipeline собран, сервис готов к обработке POST /review")
    yield
    app.state.pipeline = None
    logger.info("Pipeline освобождён")


app = FastAPI(title="Avito AI Consultant", lifespan=lifespan)


@app.exception_handler(RepoCloneError)
async def _repo_clone_error_handler(request: Request, exc: RepoCloneError) -> JSONResponse:
    logger.error("POST /review: сбой клонирования: %s", exc)
    return _error_response(422, str(exc))


@app.exception_handler(TaskParseError)
async def _task_parse_error_handler(request: Request, exc: TaskParseError) -> JSONResponse:
    logger.error("POST /review: сбой разбора условия: %s", exc)
    return _error_response(422, str(exc))


@app.exception_handler(LLMError)
async def _llm_error_handler(request: Request, exc: LLMError) -> JSONResponse:
    logger.error("POST /review: сбой LLM: %s", exc)
    return _error_response(502, str(exc))


@app.exception_handler(LLMJudgementError)
async def _llm_judgement_error_handler(request: Request, exc: LLMJudgementError) -> JSONResponse:
    logger.error("POST /review: сбой LLM-оценки детектора: %s", exc)
    return _error_response(502, str(exc))


@app.exception_handler(EvaluationError)
async def _evaluation_error_handler(request: Request, exc: EvaluationError) -> JSONResponse:
    logger.error("POST /review: сбой покритериальной оценки: %s", exc)
    return _error_response(502, str(exc))


async def _save_upload_to_temp(task_file: UploadFile, original_name: str) -> tuple[Path, Path]:
    """Сохранить UploadFile во временный каталог; имя файла — исходное (stem + расширение).

    Возвращает ``(каталог, путь к файлу)``: каталог удаляет вызывающий.
    """
    safe_stem = Path(original_name).stem or "task"
    suffix = Path(original_name).suffix.lower()
    temp_dir = Path(tempfile.mkdtemp(prefix=TASK_FILE_PREFIX))
    temp_path = temp_dir / f"{safe_stem}{suffix}"
    data = await task_file.read()
    try:
        await asyncio.to_thread(temp_path.write_bytes, data)
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return temp_dir, temp_path


@app.post("/review", response_model=ReviewResponse)
async def review(request: Request, repo_url: str = Form(...), task_file: UploadFile = File(...)) -> ReviewResponse:
    """Полная проверка: детекция AI-генерации + покритериальная оценка по условию."""
    original_name = task_file.filename or "task"
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED_TASK_EXTENSIONS:
        return _error_response(
            422,
            f"Неподдерживаемый тип файла «{suffix or 'без расширения'}»; "
            f"поддерживаются: {', '.join(sorted(SUPPORTED_TASK_EXTENSIONS))}",
        )
    pipeline: Pipeline | None = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        return _error_response(503, "Сервис ещё не готов к обработке запросов")
    temp_dir, temp_path = await _save_upload_to_temp(task_file, original_name)
    try:
        return await pipeline.run(repo_url, temp_path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
