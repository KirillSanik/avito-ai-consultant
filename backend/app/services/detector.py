import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from .contracts import AIAssessmentResult
from .llm import LLMService
from .settings import PipelineSettings


class RepositoryCloner:
    def __init__(self, settings: PipelineSettings) -> None:
        self.settings = settings

    async def clone(self, repo_url: str) -> Path:
        base_url, branch, subfolder = self._parse_source_url(repo_url)
        root = Path(tempfile.mkdtemp(prefix="ai-review-submission-"))
        target = root / "repository"
        clone_target = root / "clone" if subfolder else target
        command = ["git", "clone", "--depth", "100"]
        if branch:
            command.extend(["-b", branch])
        command.extend([self._authenticated_url(base_url), str(clone_target)])
        try:
            await asyncio.to_thread(subprocess.run, command, check=True, capture_output=True, text=True, timeout=240)
            if subfolder:
                source = clone_target.joinpath(*subfolder.split("/"))
                if not source.is_dir():
                    raise ValueError(f"Подкаталог из URL GitHub не найден: {subfolder}")
                target.mkdir(parents=True, exist_ok=True)
                for item in source.iterdir():
                    shutil.move(str(item), str(target / item.name))
                shutil.rmtree(clone_target, ignore_errors=True)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip()
            message = f"Не удалось клонировать репозиторий GitHub: {detail}" if detail else "Не удалось клонировать репозиторий GitHub"
            shutil.rmtree(root, ignore_errors=True)
            raise ValueError(message) from exc
        except (subprocess.TimeoutExpired, OSError, ValueError):
            shutil.rmtree(root, ignore_errors=True)
            raise
        return target

    def _parse_source_url(self, repo_url: str) -> tuple[str, str | None, str]:
        parts = urlsplit(repo_url.strip())
        if parts.scheme != "https" or parts.hostname not in {"github.com", "www.github.com"}:
            raise ValueError("Ожидается HTTPS-ссылка на репозиторий GitHub")
        segments = [unquote(segment) for segment in parts.path.split("/") if segment]
        if len(segments) < 2 or segments[0] in {".", ".."} or segments[1] in {".", ".."}:
            raise ValueError("Некорректная ссылка GitHub: не удалось определить owner/repository")
        owner = segments[0]
        repository = segments[1].removesuffix(".git")
        if not repository:
            raise ValueError("Некорректная ссылка GitHub: имя репозитория отсутствует")
        if len(segments) == 2:
            return f"https://github.com/{owner}/{repository}.git", None, ""
        if segments[2] != "tree" or len(segments) < 4:
            raise ValueError("Поддерживаются ссылки GitHub вида /owner/repository/tree/branch/subfolder")
        branch = segments[3]
        subfolder_segments = segments[4:]
        if not branch or any(segment in {".", ".."} for segment in subfolder_segments):
            raise ValueError("Некорректная ветка или подкаталог в ссылке GitHub")
        return f"https://github.com/{owner}/{repository}.git", branch, "/".join(subfolder_segments)

    def _authenticated_url(self, repo_url: str) -> str:
        if not self.settings.github_token:
            return repo_url
        parts = urlsplit(repo_url)
        if parts.scheme != "https" or not parts.hostname:
            return repo_url
        return urlunsplit((parts.scheme, f"x-access-token:{quote(self.settings.github_token, safe='')}@{parts.netloc}", parts.path, parts.query, parts.fragment))


class AIDetectionService:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    async def analyze(self, task_text: str, repository: Path) -> AIAssessmentResult:
        commits, tree, code = await asyncio.gather(
            asyncio.to_thread(self._commits, repository),
            asyncio.to_thread(self._tree, repository),
            asyncio.to_thread(self._code, repository),
        )
        return await self.llm.assess_ai_origin(task_text, tree, commits, code)

    def _commits(self, repository: Path) -> list[dict]:
        process = subprocess.run(["git", "log", "--pretty=format:%H%x1f%an%x1f%aI%x1f%s"], cwd=repository, capture_output=True, text=True, check=False, timeout=240)
        return [
            {"hash": parts[0], "author": parts[1], "date": parts[2], "message": parts[3]}
            for line in process.stdout.splitlines()
            if len(parts := line.split("\x1f", 3)) == 4
        ]

    def _tree(self, repository: Path) -> list[str]:
        return [str(path.relative_to(repository)) for path in repository.rglob("*") if path.is_file() and ".git" not in path.parts]

    def _code(self, repository: Path) -> str:
        supported = {".py", ".js", ".ts", ".go", ".rs", ".java", ".cpp", ".md", ".sql"}
        chunks = []
        for path in repository.rglob("*"):
            if path.is_file() and path.suffix.lower() in supported and ".git" not in path.parts:
                chunks.append(f"## {path.relative_to(repository)}\n{path.read_text(encoding='utf-8', errors='replace')}")
        return "\n\n".join(chunks)
