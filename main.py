from datetime import datetime
from pathlib import Path

import click

from src.config import AppConfig
from src.evaluator.grading_engine import GradingEngine
from src.parsers.task_parser import TaskParser
from src.parsers.submission_parser import SubmissionParser
from src.repository.evaluation_repository import EvaluationRepository
from src.repository.submission_repository import SubmissionRepository
from src.repository.task_repository import TaskRepository


@click.group()
def cli() -> None:
    pass


@cli.command("ingest-task")
@click.option("--file", "pdf_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--task-id", required=True)
@click.option("--api-base", default="http://localhost:11434/v1", show_default=True)
@click.option("--api-key", default="ollama", show_default=True)
@click.option("--model", default=None)
@click.option("--test-mode", is_flag=True, default=False)
def ingest_task(pdf_path: Path, task_id: str, api_base: str, api_key: str, model: str | None, test_mode: bool) -> None:
    config = AppConfig(test_mode=test_mode, model=model, api_base=api_base, api_key=api_key)
    parser = TaskParser(config)
    rubric = parser.parse_task(str(pdf_path), task_id)
    saved_path = TaskRepository().save(rubric)
    update_documentation_status(task_id)
    click.echo(rubric.model_dump_json(indent=2))
    click.echo(f"\nЗадание сохранено: {saved_path}")
    click.echo("Статус документации обновлён.")


@cli.command("parse-submission")
@click.option("--file", "submission_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None)
@click.option("--url", "repository_url", default=None)
@click.option("--task-id", required=True)
@click.option("--model", default=None)
@click.option("--test-mode", is_flag=True, default=False)
def parse_submission(submission_path: Path | None, repository_url: str | None, task_id: str, model: str | None, test_mode: bool) -> None:
    if bool(submission_path) == bool(repository_url):
        raise click.UsageError("Укажите ровно один источник: --file или --url")
    config = AppConfig(test_mode=test_mode, model=model)
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
@click.option("--task-id", required=True)
@click.option("--submission-id", default=None)
@click.option("--submission-file", "submission_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None)
@click.option("--api-base", default="http://localhost:11434/v1", show_default=True)
@click.option("--api-key", default="ollama", show_default=True)
@click.option("--model", default=None)
@click.option("--test-mode", is_flag=True, default=False)
def evaluate(task_id: str, submission_id: str | None, submission_path: Path | None, api_base: str, api_key: str, model: str | None, test_mode: bool) -> None:
    config = AppConfig(test_mode=test_mode, model=model, api_base=api_base, api_key=api_key)
    rubric = TaskRepository().load(task_id)
    if submission_id:
        submission = SubmissionRepository().load(submission_id)
    elif submission_path:
        submission = SubmissionParser(config, task_id).parse_submission(str(submission_path), task_id)
    else:
        raise click.UsageError("Укажите --submission-id или --submission-file")
    report = GradingEngine(config).evaluate_submission(rubric, submission, config)
    for result in report.criterion_results:
        click.echo(f"{result.criterion_name}: {result.assigned_score:g}/{result.max_points:g}")
    click.echo(f"Итого: {report.total_score:g}/{report.max_total_score:g}")
    saved_path = EvaluationRepository().storage_dir / f"{report.submission_id}.json"
    click.echo(f"Отчёт сохранён: {saved_path}")


def update_documentation_status(task_id: str) -> None:
    readme_path = Path(__file__).resolve().parent / "README.md"
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    marker = "- Статус последнего запуска:"
    replacement = f"{marker} успешно обработано задание `{task_id}` ({timestamp})."
    content = readme_path.read_text(encoding="utf-8")
    lines = [replacement if line.startswith(marker) else line for line in content.splitlines()]
    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    cli()
