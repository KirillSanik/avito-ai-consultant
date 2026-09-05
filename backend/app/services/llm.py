import asyncio
import json

from openai import AsyncOpenAI

from .contracts import AIAssessmentResult, Criterion, CriterionResult, SubmissionData, TaskRubric
from .prompts import AI_ORIGIN_SYSTEM_PROMPT, GRADING_SYSTEM_PROMPT, TASK_RUBRIC_SYSTEM_PROMPT
from .settings import PipelineSettings


class LLMService:
    def __init__(self, settings: PipelineSettings) -> None:
        self.settings = settings
        if settings.llm_provider == "ollama":
            self.client = AsyncOpenAI(base_url=settings.ollama_base_url, api_key="ollama")
            self.model = settings.ollama_model
        else:
            self.client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=settings.openrouter_api_key)
            self.model = settings.model_name

    async def parse_rubric(self, task_id: str, title: str, text: str, fallback: TaskRubric) -> TaskRubric:
        payload = await self._json(
            TASK_RUBRIC_SYSTEM_PROMPT,
            json.dumps({"task_id": task_id, "title": title, "text": text[: self.settings.max_input_chars]}, ensure_ascii=False),
        )
        return TaskRubric.model_validate({
            "task_id": task_id,
            "title": payload.get("title") or fallback.title,
            "description": payload.get("description") or fallback.description,
            "full_instructions": text,
            "guidelines": payload.get("guidelines") or fallback.guidelines,
            "criteria": payload.get("criteria") or [item.model_dump() for item in fallback.criteria],
            "constraints": payload.get("constraints") or fallback.constraints.model_dump(),
            "total_points": sum(float(item.get("max_points", 0)) for item in payload.get("criteria", [])) or fallback.total_points,
        })

    async def grade_criterion(self, criterion: Criterion, rubric: TaskRubric, submission: SubmissionData) -> CriterionResult:
        payload = await self._json(
            GRADING_SYSTEM_PROMPT,
            json.dumps({
                "criterion": criterion.model_dump(),
                "task": rubric.full_instructions[: self.settings.max_input_chars],
                "submission": submission.model_dump(mode="json"),
            }, ensure_ascii=False),
        )
        score = min(max(float(payload.get("assigned_score", 0)), 0), criterion.max_points)
        return CriterionResult(
            criterion_id=criterion.name,
            criterion_name=criterion.name,
            assigned_score=score,
            max_points=criterion.max_points,
            reasoning=str(payload.get("reasoning") or "LLM did not provide reasoning."),
            evidence=[str(item) for item in payload.get("evidence", [])],
        )

    async def assess_ai_origin(self, task_text: str, file_tree: list[str], commits: list[dict], code: str) -> AIAssessmentResult:
        payload = await self._json(
            AI_ORIGIN_SYSTEM_PROMPT,
            json.dumps({"task": task_text[:20000], "files": file_tree, "commits": commits, "code": code[: self.settings.max_input_chars]}, ensure_ascii=False),
        )
        return AIAssessmentResult(
            ai_indicators=[str(item) for item in payload.get("ai_indicators", [])],
            human_indicators=[str(item) for item in payload.get("human_indicators", [])],
            reasoning=str(payload.get("reasoning") or "AI-origin assessment unavailable."),
            status=str(payload.get("status", "yellow")).lower(),
            confidence=min(max(float(payload.get("confidence", 0)), 0), 1),
        )

    async def _json(self, system: str, user: str) -> dict:
        if self.settings.llm_provider != "ollama" and not self.settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for LLM evaluation")
        response = await self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)


async def grade_submission(llm: LLMService, rubric: TaskRubric, submission: SubmissionData):
    results = await asyncio.gather(*(llm.grade_criterion(item, rubric, submission) for item in rubric.criteria))
    return list(results)
