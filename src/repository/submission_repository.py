from pathlib import Path

from src.models.submission import SubmissionData


class SubmissionRepository:
    def __init__(self, storage_dir: str | Path | None = None) -> None:
        self.storage_dir = Path(storage_dir) if storage_dir else Path(__file__).resolve().parents[2] / "storage" / "submissions"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save(self, submission: SubmissionData) -> str:
        path = self._path_for(submission.submission_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(submission.model_dump_json(indent=2), encoding="utf-8")
        return str(path)

    def load(self, submission_id: str) -> SubmissionData:
        path = self._path_for(submission_id)
        if not path.is_file():
            raise FileNotFoundError(f"Сдача не найдена: {submission_id}")
        return SubmissionData.model_validate_json(path.read_text(encoding="utf-8"))

    def _path_for(self, submission_id: str) -> Path:
        if not submission_id or Path(submission_id).name != submission_id or submission_id in {".", ".."}:
            raise ValueError("submission_id должен быть непустым именем файла без пути")
        return self.storage_dir / f"{submission_id}.json"
