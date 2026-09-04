from pathlib import Path

import click

from homework_reviewer.config import AppConfig
from homework_reviewer.evaluator.grading_engine import GradingEngine
from homework_reviewer.parsers.submission_parser import SubmissionParser
from homework_reviewer.parsers.task_parser import TaskParser
from homework_reviewer.reports.pdf_generator import generate_evaluation_pdf
from homework_reviewer.repository.evaluation_repository import EvaluationRepository
from homework_reviewer.repository.submission_repository import SubmissionRepository
from homework_reviewer.repository.task_repository import TaskRepository


@click.group()
def cli() -> None:
    pass


@cli.command("ingest-task")
@click.option("--file", "pdf_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--task-id", required=True)
@click.option("-p", "--provider", "llm_provider", type=click.Choice(["openrouter", "ollama"]), default="openrouter", show_default=True)
@click.option("--api-base", default=None)
@click.option("--api-key", default=None)
@click.option("--model", default=None)
@click.option("--model-name", default=None)
@click.option("--test-mode", is_flag=True, default=False)
def ingest_task(pdf_path: Path, task_id: str, llm_provider: str, api_base: str | None, api_key: str | None, model: str | None, model_name: str | None, test_mode: bool) -> None:
    config = AppConfig(test_mode=test_mode, llm_provider=llm_provider, model=model_name or model, api_base=api_base, api_key=api_key)
    parser = TaskParser(config)
    rubric = parser.parse_task(str(pdf_path), task_id)
    saved_path = TaskRepository().save(rubric)
    click.echo(rubric.model_dump_json(indent=2))
    click.echo(f"\nЗадание сохранено: {saved_path}")


@cli.command("parse-submission")
@click.option("--file", "submission_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None)
@click.option("--url", "repository_url", default=None)
@click.option("--task-id", required=True)
@click.option("-p", "--provider", "llm_provider", type=click.Choice(["openrouter", "ollama"]), default="openrouter", show_default=True)
@click.option("--model", default=None)
@click.option("--model-name", default=None)
@click.option("--test-mode", is_flag=True, default=False)
def parse_submission(submission_path: Path | None, repository_url: str | None, task_id: str, llm_provider: str, model: str | None, model_name: str | None, test_mode: bool) -> None:
    if bool(submission_path) == bool(repository_url):
        raise click.UsageError("Укажите ровно один источник: --file или --url")
    config = AppConfig(test_mode=test_mode, llm_provider=llm_provider, model=model_name or model)
    parser = SubmissionParser(config, task_id)
    if repository_url:
        submission = parser.parse_github_repository(repository_url)
    else:
        submission = parser.parse_submission(str(submission_path), task_id)
    saved_path = SubmissionRepository().save(submission)
    click.echo(f"Тип файла: {submission.file_type}")
    click.echo(f"Длина извлечённого текста: {len(submission.raw_text)}")
    click.echo(f"Таблиц: {len(submission.tables)}; изображений: {submission.image_count}")
    if submission.excel_audit:
        audit = submission.excel_audit
        click.echo(f"Excel: листов {len(audit.sheet_names)}, строк {audit.total_rows}, формул {audit.formula_count}, констант {audit.hardcoded_count}")
    for link in submission.resolved_links:
        status = "доступна" if link.is_accessible else "недоступна"
        click.echo(f"Ссылка {status}: HTTP {link.status_code} — {link.url}")
    click.echo(f"Сдача сохранена: {saved_path}")


@cli.command("evaluate")
@click.option("--task-id", default=None)
@click.option("--submission-id", default=None)
@click.option("--submission-file", "submission_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None)
@click.option("-p", "--provider", "llm_provider", type=click.Choice(["openrouter", "ollama"]), default="openrouter", show_default=True)
@click.option("--api-base", default=None)
@click.option("--api-key", default=None)
@click.option("--model", default=None)
@click.option("--model-name", default=None)
@click.option("--test-mode", is_flag=True, default=False)
@click.option("--pdf", "generate_pdf", is_flag=True, default=False)
def evaluate(task_id: str | None, submission_id: str | None, submission_path: Path | None, llm_provider: str, api_base: str | None, api_key: str | None, model: str | None, model_name: str | None, test_mode: bool, generate_pdf: bool) -> None:
    if test_mode:
        task_id = task_id or "task1"
        submission_id = submission_id or "test_repo_ds"
    if not task_id:
        raise click.UsageError("--task-id is required outside test mode")
    config = AppConfig(test_mode=test_mode, llm_provider=llm_provider, model=model_name or model, api_base=api_base, api_key=api_key)
    rubric = TaskRepository().load(task_id)
    if submission_id:
        submission = SubmissionRepository().load(submission_id)
    elif submission_path:
        submission = SubmissionParser(config, task_id).parse_submission(str(submission_path), task_id)
    else:
        raise click.UsageError("Укажите --submission-id или --submission-file")
    try:
        report = GradingEngine(config).evaluate_submission(rubric, submission, config)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    for result in report.criterion_results:
        click.echo(f"{result.criterion_name}: {result.assigned_score:g}/{result.max_points:g}")
    click.echo(f"Итого: {report.total_score:g}/{report.max_total_score:g}")
    saved_path = EvaluationRepository().storage_dir / f"{report.submission_id}.json"
    click.echo(f"Отчёт сохранён: {saved_path}")
    if generate_pdf:
        output_path = EvaluationRepository().storage_dir.parent / "reports" / f"{report.submission_id}.pdf"
        click.echo(f"PDF отчёт: {generate_evaluation_pdf(str(saved_path), str(output_path))}")


@cli.command("generate-pdf")
@click.option("--eval-json", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), default=None)
def generate_pdf(eval_json: Path, output: Path | None) -> None:
    output_path = output or (Path(__file__).resolve().parent / "storage" / "reports" / f"{eval_json.stem}.pdf")
    click.echo(f"PDF отчёт: {generate_evaluation_pdf(str(eval_json), str(output_path))}")


if __name__ == "__main__":
    cli()
