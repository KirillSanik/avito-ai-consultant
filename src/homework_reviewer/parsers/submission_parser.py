"""Разбор сдач студентов: локальные файлы (xlsx/docx/pdf) и GitHub-репозитории.

Клонирование и чтение файлов — изолированы: ``build_from_local_repository``
работает с **уже клонированным** репозиторием (используется и CLI, и
``GradingEngine.evaluate_from_path``), а ``parse_github_repository`` сама
делает временный shallow-клон для CLI-сценария.
"""

import re
import subprocess
import tempfile
from pathlib import Path
from typing import ClassVar
from urllib.parse import quote, urlparse, urlunparse

import pdfplumber

from common.models import SubmissionData
from common.parsers.docx_parser import DOCXParser
from common.parsers.xlsx_parser import XLSXParser
from common.settings import Settings, get_settings
from homework_reviewer.parsers.link_parser import LinkParser


class SubmissionParser:
    ignored_directories: ClassVar[frozenset[str]] = frozenset(
        {"data", "dataset", "datasets", "rawdata", "artifacts", "logs", "cache", "git", "venv", "pycache"}
    )
    ignored_extensions: ClassVar[frozenset[str]] = frozenset(
        {
            ".csv", ".parquet", ".feather", ".h5", ".hdf5", ".pkl", ".npy", ".npz", ".db", ".sqlite",
            ".zip", ".tar", ".exe", ".png", ".jpg",
        }
    )
    supported_repository_extensions: ClassVar[frozenset[str]] = frozenset(
        {".py", ".ipynb", ".sql", ".sh", ".go", ".md", ".docx", ".pdf", ".xlsx"}
    )
    excluded_task_names: ClassVar[frozenset[str]] = frozenset(
        {"описаниезадания", "taskdescription", "assignmentdescription"}
    )

    def __init__(self, settings: Settings | None = None, task_id: str = "") -> None:
        self.settings = settings or get_settings()
        self.task_id = task_id
        self.link_parser = LinkParser()
        self.parsers = {".xlsx": XLSXParser(), ".docx": DOCXParser()}

    def parse_submission(self, file_path: str, task_id: str) -> SubmissionData:
        source = Path(file_path)
        if not source.is_file():
            raise FileNotFoundError(f"Файл решения не найден: {file_path}")
        extension = source.suffix.lower()
        if extension == ".pdf":
            parsed = self._parse_pdf(str(source))
        elif extension in self.parsers:
            parsed = self.parsers[extension].parse(str(source))
        else:
            raise ValueError("Поддерживаются только файлы .xlsx, .docx и .pdf.")
        urls = self.link_parser.extract_urls(parsed["raw_text"])
        urls.extend(parsed["links"])
        unique_urls = list(dict.fromkeys(urls))
        return SubmissionData(
            submission_id=source.stem,
            task_id=task_id,
            file_type=extension.removeprefix("."),
            file_tree=[source.name],
            raw_text=parsed["raw_text"],
            tables=parsed["tables"],
            excel_audit=parsed["excel_audit"],
            resolved_links=[self.link_parser.resolve_link(url) for url in unique_urls],
            image_count=parsed["image_count"],
        )

    def build_from_local_repository(self, repository_root: Path, submission_id: str, task_id: str) -> SubmissionData:
        """Собирает ``SubmissionData`` из уже клонированного локального репозитория.

        Без клонирования: ``repository_root`` должен содержать рабочую копию
        (используется ``Pipeline``/``GradingEngine.evaluate_from_path``).
        Синхронный метод — в async-контексте вызывать через ``asyncio.to_thread``.
        """
        repository_root = Path(repository_root)
        if not (repository_root / ".git").exists():
            raise FileNotFoundError(f"Каталог не является git-репозиторием: {repository_root}")
        included_files = self._repository_files(repository_root)
        file_tree = [path.relative_to(repository_root).as_posix() for path in included_files]
        tree_text = "\n".join(file_tree)
        file_blocks: list[str] = []
        tables: list[dict] = []
        links: list[str] = []
        image_count = 0
        for path in included_files:
            relative_path = path.relative_to(repository_root).as_posix()
            parsed = self._parse_repository_file(path)
            content = parsed["raw_text"]
            file_blocks.append(f"=== FILE: {relative_path} ===\n{content}\n=== END FILE: {relative_path} ===")
            tables.extend(parsed["tables"])
            links.extend(parsed["links"])
            image_count += parsed["image_count"]
        raw_text = f"Repository tree:\n{tree_text}"
        if file_blocks:
            raw_text = f"{raw_text}\n\n" + "\n\n".join(file_blocks)
        links.extend(self.link_parser.extract_urls(raw_text))
        unique_urls = list(dict.fromkeys(links))
        return SubmissionData(
            submission_id=submission_id,
            task_id=task_id,
            file_type="github",
            file_tree=file_tree,
            raw_text=raw_text,
            tables=tables,
            resolved_links=[self.link_parser.resolve_link(url) for url in unique_urls],
            image_count=image_count,
        )

    def parse_github_repository(self, repo_url: str) -> SubmissionData:
        clone_url = self._authenticated_clone_url(repo_url)
        repository_name = Path(urlparse(repo_url).path).stem or "github-repository"
        with tempfile.TemporaryDirectory(prefix="submission-repository-") as temporary_directory:
            repository_root = Path(temporary_directory) / "repository"
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", clone_url, str(repository_root)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                message = (exc.stderr or exc.stdout or "git clone завершился ошибкой").replace(clone_url, repo_url)
                if self.settings.git_token:
                    message = message.replace(self.settings.git_token, "***")
                raise RuntimeError(f"Не удалось клонировать GitHub-репозиторий: {message.strip()}") from exc
            return self.build_from_local_repository(repository_root, repository_name, self.task_id)

    def _authenticated_clone_url(self, repo_url: str) -> str:
        parsed = urlparse(repo_url)
        if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
            raise ValueError("Поддерживаются только HTTPS-ссылки на GitHub-репозитории.")
        if not self.settings.git_token:
            return repo_url
        hostname = parsed.hostname or "github.com"
        netloc = f"{quote(self.settings.git_token, safe='')}@{hostname}"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urlunparse(parsed._replace(netloc=netloc))

    def _repository_files(self, repository_root: Path) -> list[Path]:
        included_files: list[Path] = []
        for path in sorted(repository_root.rglob("*")):
            relative_parts = path.relative_to(repository_root).parts
            if any(self._normalize_name(part) in self.ignored_directories for part in relative_parts[:-1]):
                continue
            if not path.is_file() or path.suffix.lower() not in self.supported_repository_extensions:
                continue
            if path.suffix.lower() in self.ignored_extensions or path.stat().st_size > 1024 * 1024:
                continue
            normalized_name = self._normalize_name(path.stem)
            if any(excluded_name in normalized_name for excluded_name in self.excluded_task_names):
                continue
            included_files.append(path)
        return included_files

    def _parse_repository_file(self, path: Path) -> dict:
        extension = path.suffix.lower()
        if extension == ".pdf":
            return self._parse_pdf(str(path))
        if extension in self.parsers:
            return self.parsers[extension].parse(str(path))
        return {
            "raw_text": path.read_text(encoding="utf-8", errors="replace"),
            "tables": [],
            "links": [],
            "excel_audit": None,
            "image_count": 0,
        }

    @staticmethod
    def _normalize_name(value: str) -> str:
        return re.sub(r"[^\w]+", "", value, flags=re.UNICODE).replace("_", "").lower()

    @staticmethod
    def _parse_pdf(file_path: str) -> dict:
        parts: list[str] = []
        tables: list[dict] = []
        links: list[str] = []
        image_count = 0
        with pdfplumber.open(file_path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                if text:
                    parts.append(f"## Страница {page_number}\n{text}")
                for table_number, table in enumerate(page.extract_tables(), start=1):
                    rows = [[cell or "" for cell in row] for row in table if row]
                    tables.append({"page": page_number, "table": table_number, "rows": rows})
                image_count += len(page.images)
                for annotation in page.annots or []:
                    uri = annotation.get("uri")
                    if uri:
                        links.append(uri)
        return {
            "raw_text": "\n\n".join(parts),
            "tables": tables,
            "links": links,
            "excel_audit": None,
            "image_count": image_count,
        }
