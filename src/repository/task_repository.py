from pathlib import Path

from src.models.rubric import TaskRubric


class TaskRepository:
    def __init__(self, storage_dir: str | Path | None = None) -> None:
        self.storage_dir = Path(storage_dir) if storage_dir else Path(__file__).resolve().parents[2] / "storage" / "tasks"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save(self, rubric: TaskRubric) -> str:
        path = self._path_for(rubric.task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rubric.model_dump_json(indent=2), encoding="utf-8")
        return str(path)

    def load(self, task_id: str) -> TaskRubric:
        path = self._path_for(task_id)
        if not path.is_file():
            raise FileNotFoundError(f"Задание не найдено: {task_id}")
        return TaskRubric.model_validate_json(path.read_text(encoding="utf-8"))

    def _path_for(self, task_id: str) -> Path:
        if not task_id or Path(task_id).name != task_id or task_id in {".", ".."}:
            raise ValueError("task_id должен быть непустым именем файла без пути")
        return self.storage_dir / f"{task_id}.json"
