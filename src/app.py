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
import subprocess
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from ai_detector.service import AIDetectionService
from common.clients import get_llm_client, get_openrouter_client
from common.db.models import Course, Evaluation, Submission, SubmissionStatus, Task, User, UserRole
from common.db.session import get_session, init_db
from common.models import TaskCriteria, TaskRubric
from common.parsers import SUPPORTED_TASK_EXTENSIONS, extract_task_text, parse_task_rubric
from common.settings import get_settings
from core.pipeline import Pipeline
from homework_reviewer.evaluator.grading_engine import GradingEngine
from homework_reviewer.reports.pdf_generator import generate_review_pdf

logger = logging.getLogger(__name__)

#: Префикс temp-каталога загруженных условий (тот же стиль, что у ``core.repo_clone.TEMP_DIR_PREFIX``).
TASK_FILE_PREFIX = "avito-review-task-"


def _error_response(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Старт: сборка Pipeline из фабрик клиентов; стоп: сброс состояния."""
    settings = get_settings()
    detector_service = AIDetectionService(get_llm_client(settings), settings)
    reviewer_service = GradingEngine(get_openrouter_client(settings), settings)
    app.state.pipeline = Pipeline(
        detector=detector_service,
        reviewer=reviewer_service,
        settings=settings,
    )
    storage_root = await asyncio.to_thread(lambda: Path(settings.storage_dir).resolve())
    for directory in (storage_root / "tasks", storage_root / "submissions", storage_root / "reports"):
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
    init_db(settings.database_url)
    app.state.storage_root = storage_root
    logger.info("Pipeline собран, сервис готов к обработке POST /review")
    yield
    app.state.pipeline = None
    logger.info("Pipeline освобождён")


app = FastAPI(title="Avito AI Consultant", lifespan=lifespan)


def _safe_id(value: str, field: str) -> str:
    if not value or Path(value).name != value or value in {".", ".."}:
        raise HTTPException(422, f"{field} должен быть непустым идентификатором без пути")
    return value


async def _store_upload(upload: UploadFile, directory: Path, entity_id: str) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if not suffix:
        raise HTTPException(422, "У загруженного файла должно быть расширение")
    path = directory / f"{entity_id}{suffix}"
    try:
        await asyncio.to_thread(path.write_bytes, await upload.read())
    except OSError as exc:
        raise HTTPException(500, "Не удалось сохранить загруженный файл") from exc
    return path


async def _download_task_file(url: str, directory: Path, entity_id: str) -> Path:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if parsed.scheme not in {"http", "https"} or suffix not in SUPPORTED_TASK_EXTENSIONS:
        raise HTTPException(422, f"url должен быть HTTP(S)-ссылкой на {', '.join(sorted(SUPPORTED_TASK_EXTENSIONS))}")

    def _download() -> bytes:
        with urlopen(url, timeout=20) as response:
            return response.read()

    try:
        data = await asyncio.to_thread(_download)
        path = directory / f"{entity_id}{suffix}"
        await asyncio.to_thread(path.write_bytes, data)
        return path
    except OSError as exc:
        raise HTTPException(422, "Не удалось скачать файл условия по url") from exc


async def _make_uploaded_solution_repo(source: Path, submission_id: str) -> tuple[Path, Path]:
    """Materialize one uploaded source file as a disposable Git repository."""
    temp_root = Path(tempfile.mkdtemp(prefix="avito-uploaded-submission-"))
    repo = temp_root / "repo"
    repo.mkdir()
    await asyncio.to_thread(shutil.copy2, source, repo / source.name)
    # The detector consumes text/code files. Preserve a textual companion for
    # office-format uploads so a DOCX/PDF/XLSX submission can use the same
    # repository pipeline as a source-code submission.
    if source.suffix.lower() in {".pdf", ".docx", ".xlsx"}:
        extracted = await asyncio.to_thread(extract_task_text, source)
        await asyncio.to_thread((repo / "submission_content.md").write_text, extracted, encoding="utf-8")

    def _git() -> None:
        for args in (
            ("git", "init"),
            ("git", "add", source.name),
            (
                "git", "-c", "user.name=Upload", "-c", "user.email=upload@local", "commit", "-m",
                f"submission {submission_id}",
            ),
        ):
            subprocess.run(args, cwd=repo, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        await asyncio.to_thread(_git)
    except (OSError, subprocess.CalledProcessError) as exc:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise HTTPException(500, "Не удалось подготовить загруженную сдачу к проверке") from exc
    return temp_root, repo


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness endpoint; does not call the database or an LLM."""
    return {"status": "ok"}


@app.post("/api/v1/users/register", status_code=201)
async def register_user(
    user_id: str = Form(...), role: UserRole = Form(...), name: str = Form(...), session: Session = Depends(get_session)
) -> dict:
    user_id = _safe_id(user_id, "user_id")
    if session.get(User, user_id):
        raise HTTPException(409, "Пользователь с таким user_id уже существует")
    session.add(User(id=user_id, role=role, name=name))
    session.commit()
    return {"id": user_id, "role": role.value, "name": name}


@app.post("/api/v1/tasks", status_code=201)
async def create_task(
    request: Request,
    course_id: str = Form(...),
    title: str = Form(...),
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
    session: Session = Depends(get_session),
) -> dict:
    if bool(file) == bool(url):
        raise HTTPException(422, "Укажите ровно один источник условия: file или url")
    course_id = _safe_id(course_id, "course_id")
    task_id = str(uuid.uuid4())
    storage = request.app.state.storage_root / "tasks"
    source = (
        await _store_upload(file, storage, task_id)
        if file
        else await _download_task_file(url or "", storage, task_id)
    )
    if source.suffix.lower() not in SUPPORTED_TASK_EXTENSIONS:
        source.unlink(missing_ok=True)
        raise HTTPException(
            422,
            "Для API tasks поддерживаются только "
            f"{', '.join(sorted(SUPPORTED_TASK_EXTENSIONS))}",
        )
    try:
        text = await asyncio.to_thread(extract_task_text, source)
        rubric = await parse_task_rubric(
            text,
            task_id,
            client=request.app.state.pipeline._rubric_client(),
            settings=get_settings(),
        )
    except Exception:
        source.unlink(missing_ok=True)
        raise
    if session.get(Course, course_id) is None:
        session.add(Course(id=course_id, title=course_id))
    session.add(
        Task(
            id=task_id,
            course_id=course_id,
            title=title,
            rubric_json=rubric.model_dump(mode="json"),
            file_path=str(source),
        )
    )
    session.commit()
    return {"id": task_id, "course_id": course_id, "title": title, "rubric_json": rubric.model_dump(mode="json")}


@app.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str, session: Session = Depends(get_session)) -> dict:
    task_id = _safe_id(task_id, "task_id")
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "Задание не найдено")
    return {
        "id": task.id,
        "course_id": task.course_id,
        "title": task.title,
        "rubric_json": task.rubric_json,
        "file_path": task.file_path,
    }


@app.post("/api/v1/submissions", status_code=201)
async def create_submission(
    request: Request,
    task_id: str = Form(...),
    student_id: str = Form(...),
    repo_url: str | None = Form(None),
    file: UploadFile | None = File(None),
    session: Session = Depends(get_session),
) -> dict:
    if bool(repo_url) == bool(file):
        raise HTTPException(422, "Укажите ровно один источник сдачи: repo_url или file")
    task_id, student_id = _safe_id(task_id, "task_id"), _safe_id(student_id, "student_id")
    task, student = session.get(Task, task_id), session.get(User, student_id)
    if task is None or student is None:
        raise HTTPException(404, "Задание или студент не найдены")
    if student.role != UserRole.STUDENT:
        raise HTTPException(422, "student_id должен принадлежать пользователю с ролью student")
    submission_id = str(uuid.uuid4())
    saved_file: Path | None = None
    if file:
        saved_file = await _store_upload(file, request.app.state.storage_root / "submissions", submission_id)
    submission = Submission(
        id=submission_id,
        task_id=task_id,
        student_id=student_id,
        repo_url=repo_url,
        file_path=str(saved_file) if saved_file else None,
        status=SubmissionStatus.PROCESSING,
    )
    session.add(submission)
    session.commit()
    rubric = TaskRubric.model_validate(task.rubric_json)
    criteria = TaskCriteria(task_id=task_id, text=rubric.full_instructions, rubric=rubric)
    try:
        pipeline: Pipeline = request.app.state.pipeline
        if repo_url:
            review_result = await pipeline.run_preparsed(repo_url, criteria)
        else:
            temp_root, repo = await _make_uploaded_solution_repo(saved_file, submission_id)  # type: ignore[arg-type]
            try:
                review_result = await pipeline.run_from_path(f"upload://{submission_id}", criteria, repo)
            finally:
                shutil.rmtree(temp_root, ignore_errors=True)
        pdf_path = request.app.state.storage_root / "reports" / f"{submission_id}.pdf"
        await asyncio.to_thread(
            generate_review_pdf,
            review_result.evaluation,
            rubric,
            str(pdf_path),
            review_result.ai_assessment,
        )
        session.add(
            Evaluation(
                id=str(uuid.uuid4()),
                submission_id=submission_id,
                review_json=review_result.model_dump(mode="json"),
                pdf_path=str(pdf_path),
            )
        )
        submission.status = SubmissionStatus.COMPLETED
        session.commit()
    except Exception:
        submission.status = SubmissionStatus.FAILED
        session.commit()
        raise
    return {
        "submission_id": submission_id,
        "status": submission.status.value,
        "review_json": review_result.model_dump(mode="json"),
        "pdf_url": f"/api/v1/evaluations/{submission_id}/pdf",
    }


@app.get("/api/v1/submissions/{submission_id}")
async def get_submission(submission_id: str, session: Session = Depends(get_session)) -> dict:
    submission_id = _safe_id(submission_id, "submission_id")
    submission = session.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(404, "Сдача не найдена")
    return {
        "id": submission.id,
        "task_id": submission.task_id,
        "student_id": submission.student_id,
        "repo_url": submission.repo_url,
        "file_path": submission.file_path,
        "status": submission.status.value,
    }


@app.get("/api/v1/evaluations")
async def get_evaluation(submission_id: str, session: Session = Depends(get_session)) -> dict:
    submission_id = _safe_id(submission_id, "submission_id")
    evaluation = session.query(Evaluation).filter(Evaluation.submission_id == submission_id).one_or_none()
    if evaluation is None:
        raise HTTPException(404, "Оценка не найдена")
    return {
        "submission_id": submission_id,
        "review_json": evaluation.review_json,
        "pdf_url": f"/api/v1/evaluations/{submission_id}/pdf",
    }


@app.get("/api/v1/evaluations/{submission_id}/pdf")
async def get_evaluation_pdf(submission_id: str, session: Session = Depends(get_session)) -> FileResponse:
    submission_id = _safe_id(submission_id, "submission_id")
    evaluation = session.query(Evaluation).filter(Evaluation.submission_id == submission_id).one_or_none()
    if evaluation is None or not await asyncio.to_thread(Path(evaluation.pdf_path).is_file):
        raise HTTPException(404, "PDF отчёт не найден")
    return FileResponse(evaluation.pdf_path, media_type="application/pdf", filename=f"{submission_id}.pdf")
