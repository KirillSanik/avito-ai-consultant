import asyncio
import json
import logging

from openai import AsyncOpenAI

from .contracts import (
    AIAssessmentResult,
    Constraints,
    CriterionResult,
    SubmissionData,
    TaskRubric,
)
from .prompts import AI_ORIGIN_SYSTEM_PROMPT, GRADING_SYSTEM_PROMPT, TASK_RUBRIC_SYSTEM_PROMPT
from .settings import PipelineSettings

logger = logging.getLogger(__name__)


def _normalize_str_list(payload: object, fallback: list[str]) -> list[str]:
    """Приводит список строк из ответа LLM к list[str]; иначе — fallback."""
    if isinstance(payload, list):
        return [str(item).strip() for item in payload if str(item).strip()]
    if isinstance(payload, str) and payload.strip():
        return [payload.strip()]
    return list(fallback)


def _normalize_constraints(payload: object, fallback: Constraints) -> Constraints:
    """Нормализует constraints из ответа LLM в модель Constraints.

    Модель иногда отдаёт плоский список строк вместо словаря полей;
    такие пункты складываем в additional_requirements.
    """
    if isinstance(payload, dict):
        try:
            return Constraints.model_validate(payload)
        except Exception:
            return fallback
    if isinstance(payload, list):
        items = [str(item).strip() for item in payload if str(item).strip()]
        if items:
            return Constraints(additional_requirements=items)
    return fallback


class LLMService:
    def __init__(self, settings: PipelineSettings) -> None:
        self.settings = settings
        if self.is_local:
            self.client = AsyncOpenAI(base_url=settings.ollama_base_url, api_key="ollama")
            self.model = settings.ollama_model
        else:
            self.client = AsyncOpenAI(
                base_url=settings.polza_base_url,
                api_key=settings.polza_api_key or "missing-polza-api-key",
            )
            self.model = settings.model_name

    @property
    def is_local(self) -> bool:
        """True для локального провайдера (local/ollama), иначе — облако (cloud/polza)."""
        return self.settings.llm_provider in ("local", "ollama")

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
            "guidelines": _normalize_str_list(payload.get("guidelines"), fallback.guidelines),
            "criteria": payload.get("criteria") or [item.model_dump() for item in fallback.criteria],
            "constraints": _normalize_constraints(payload.get("constraints"), fallback.constraints).model_dump(),
            "total_points": sum(float(item.get("max_points", 0)) for item in payload.get("criteria", [])) or fallback.total_points,
        })

    async def grade_criteria(self, rubric: TaskRubric, submission: SubmissionData) -> list[CriterionResult]:
        payload = await self._json(
            GRADING_SYSTEM_PROMPT,
            json.dumps({
                "criteria": [item.model_dump() for item in rubric.criteria],
                "task": rubric.full_instructions[: self.settings.max_input_chars],
                "submission": submission.model_dump(mode="json"),
            }, ensure_ascii=False),
        )
        by_id = {str(item.get("criterion_id")): item for item in payload.get("criteria", []) if isinstance(item, dict)}
        results: list[CriterionResult] = []
        for criterion in rubric.criteria:
            item = by_id.get(criterion.name, {})
            score = min(max(float(item.get("assigned_score", 0)), 0), criterion.max_points)
            evidence = item.get("evidence", [])
            if isinstance(evidence, str):
                evidence = [evidence]
            results.append(CriterionResult(
                criterion_id=criterion.name,
                criterion_name=criterion.name,
                assigned_score=score,
                max_points=criterion.max_points,
                reasoning=str(item.get("reasoning") or "LLM did not provide reasoning."),
                evidence=[str(e) for e in evidence],
            ))
        return results

    async def assess_ai_origin(self, task_text: str, file_tree: list[str], commits: list[dict], code: str) -> AIAssessmentResult:
        payload = await self._json(
            AI_ORIGIN_SYSTEM_PROMPT,
            json.dumps({"task": task_text[:20000], "files": file_tree, "commits": commits, "code": code[: self.settings.max_input_chars]}, ensure_ascii=False),
        )
        return AIAssessmentResult(
            ai_indicators=_normalize_str_list(payload.get("ai_indicators"), []),
            human_indicators=_normalize_str_list(payload.get("human_indicators"), []),
            reasoning=str(payload.get("reasoning") or "AI-origin assessment unavailable."),
            status=str(payload.get("status", "yellow")).lower(),
            confidence=min(max(float(payload.get("confidence", 0)), 0), 1),
        )

    async def _json(self, system: str, user: str) -> dict:
        if not self.is_local and not self.settings.polza_api_key:
            raise RuntimeError("POLZA_API_KEY is required for cloud model evaluation")
        response = await self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        content = response.choices[0].message.content or "{}"
        logger.info(
            "LLM response: model=%s usage=%s content_len=%d content=%s",
            response.model or self.model,
            response.usage,
            len(content),
            content[:500],
        )
        return json.loads(content)


async def grade_submission(llm: LLMService, rubric: TaskRubric, submission: SubmissionData):
    return await llm.grade_criteria(rubric, submission)
