import asyncio
import shutil
from pathlib import Path

from .contracts import AIAssessmentResult, CriterionResult, EvaluationReport, ReviewResponse, SubmissionData, TaskRubric
from .detector import AIDetectionService, RepositoryCloner
from .llm import LLMService, grade_submission
from .settings import PipelineSettings
from .submissions import SubmissionParser


class EvaluationPipeline:
    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self.settings = settings or PipelineSettings.from_environment()
        self.llm = LLMService(self.settings)
        self.cloner = RepositoryCloner(self.settings)
        self.detector = AIDetectionService(self.llm)
        self.submissions = SubmissionParser()

    async def run(self, submission_id: str, source_type: str, source: str, rubric: TaskRubric) -> ReviewResponse:
        if source_type == "file":
            path = Path(source)
            submission = await asyncio.to_thread(self.submissions.parse_file, path, submission_id, rubric.task_id)
            ai_assessment = await self._assess_ai_origin(rubric, submission, [], submission.raw_text)
        else:
            repository = await self.cloner.clone(source)
            try:
                submission = await asyncio.to_thread(
                    self.submissions.build_from_local_repository, repository, submission_id, rubric.task_id
                )
                commits = await asyncio.to_thread(self.detector._commits, repository)
                ai_assessment = await self._assess_ai_origin(
                    rubric, submission, commits, submission.raw_text
                )
            finally:
                shutil.rmtree(repository.parent, ignore_errors=True)
        results = await self._grade_submission(rubric, submission)
        total = sum(item.assigned_score for item in results)
        maximum = sum(item.max_points for item in results)
        report = EvaluationReport(task_id=rubric.task_id, submission_id=submission_id, total_score=total, max_total_score=maximum, criterion_results=results, summary_feedback=self._summary(results, total, maximum))
        return ReviewResponse(repo_url=source, task_id=rubric.task_id, ai_assessment=ai_assessment, evaluation=report)

    async def _assess_ai_origin(
        self, rubric: TaskRubric, submission: SubmissionData, commits: list[dict], code: str
    ) -> AIAssessmentResult:
        try:
            return await self.llm.assess_ai_origin(rubric.full_instructions, submission.file_tree, commits, code)
        except Exception as exc:
            return AIAssessmentResult(
                status="yellow",
                confidence=0,
                ai_indicators=[],
                human_indicators=["Репозиторий и файлы успешно проанализированы."],
                reasoning=f"AI-анализ происхождения временно недоступен: {exc}",
            )

    async def _grade_submission(self, rubric: TaskRubric, submission: SubmissionData) -> list[CriterionResult]:
        try:
            return await grade_submission(self.llm, rubric, submission)
        except Exception as exc:
            return [
                CriterionResult(
                    criterion_id=criterion.name,
                    criterion_name=criterion.name,
                    assigned_score=0,
                    max_points=criterion.max_points,
                    reasoning=f"Автоматическая оценка временно недоступна: {exc}",
                    evidence=[],
                )
                for criterion in rubric.criteria
            ]

    def _summary(self, results, total: float, maximum: float) -> str:
        details = " ".join(f"{item.criterion_name}: {item.assigned_score:g}/{item.max_points:g}." for item in results)
        return f"Итог: {total:g}/{maximum:g}. {details}".strip()
