from pathlib import Path

from common.models import EvaluationReport


class EvaluationRepository:
    def __init__(self, storage_dir: str | Path | None = None) -> None:
        default_dir = Path(__file__).resolve().parents[2] / "storage" / "evaluations"
        self.storage_dir = Path(storage_dir) if storage_dir else default_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save(self, report: EvaluationReport) -> str:
        path = self._path_for(report.submission_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return str(path)

    def load(self, submission_id: str) -> EvaluationReport:
        path = self._path_for(submission_id)
        if not path.is_file():
            raise FileNotFoundError(f"Результат проверки не найден: {submission_id}")
        return EvaluationReport.model_validate_json(path.read_text(encoding="utf-8"))

    def _path_for(self, submission_id: str) -> Path:
        if not submission_id or Path(submission_id).name != submission_id or submission_id in {".", ".."}:
            raise ValueError("submission_id должен быть непустым именем файла без пути")
        return self.storage_dir / f"{submission_id}.json"
