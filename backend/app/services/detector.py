import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from .contracts import AIAssessmentResult
from .llm import LLMService
from .settings import PipelineSettings


class RepositoryCloner:
    def __init__(self, settings: PipelineSettings) -> None:
        self.settings = settings

    async def clone(self, repo_url: str) -> Path:
        root = Path(tempfile.mkdtemp(prefix="ai-review-submission-"))
        target = root / "repository"
        url = self._authenticated_url(repo_url)
        try:
            await asyncio.to_thread(subprocess.run, ["git", "clone", "--depth", "100", url, str(target)], check=True, capture_output=True, timeout=120)
        except BaseException:
            shutil.rmtree(root, ignore_errors=True)
            raise
        return target

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
        process = subprocess.run(["git", "log", "--pretty=format:%H%x1f%an%x1f%aI%x1f%s"], cwd=repository, capture_output=True, text=True, check=False, timeout=30)
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
