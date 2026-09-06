import asyncio
import json
import logging

from openai import APIError, APIStatusError, AsyncOpenAI
from pydantic import ValidationError

from .contracts import (
    AIAssessmentResult,
    Constraints,
    Criterion,
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
        raw_criteria = payload.get("criteria") if isinstance(payload.get("criteria"), list) else []
        criteria = _normalize_criteria(raw_criteria, fallback.criteria)
        rubric_payload = {
            "task_id": task_id,
            "title": payload.get("title") or fallback.title,
            "description": payload.get("description") or fallback.description,
            "full_instructions": text,
            "guidelines": _normalize_str_list(payload.get("guidelines"), fallback.guidelines),
            "criteria": criteria,
            "constraints": _normalize_constraints(payload.get("constraints"), fallback.constraints).model_dump(),
            "total_points": sum(_criterion_max_points(item) for item in criteria) or fallback.total_points,
        }
        try:
            return TaskRubric.model_validate(rubric_payload)
        except ValidationError as exc:
            logger.exception("Rubric schema validation failed fields=%s", exc.errors())
            raise

    async def grade_criteria(self, rubric: TaskRubric, submission: SubmissionData) -> list[CriterionResult]:
        criteria_payload = [
            {**criterion.model_dump(), "criterion_id": str(index), "criteria_id": str(index)}
            for index, criterion in enumerate(rubric.criteria)
        ]
        payload = await self._json(
            GRADING_SYSTEM_PROMPT,
            json.dumps({
                "criteria": criteria_payload,
                "task": rubric.full_instructions[: self.settings.max_input_chars],
                "submission": self._bounded_submission(submission),
            }, ensure_ascii=False),
        )
        raw_items = (
            payload.get("criteria", payload.get("criteria_breakdown", []))
            if isinstance(payload, dict)
            else []
        )
        if not isinstance(raw_items, list):
            logger.error("LLM criteria payload has invalid field criteria: expected list, got %s", type(raw_items).__name__)
            raw_items = []
        by_id = {}
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            identifier = item.get("criterion_id", item.get("criteria_id", item.get("id")))
            if identifier is not None:
                by_id[str(identifier)] = item
        response_ids = set(by_id)
        zero_based_ids = {str(index) for index in range(len(rubric.criteria))}
        one_based_ids = {str(index + 1) for index in range(len(rubric.criteria))}
        id_offset = 0 if zero_based_ids.issubset(response_ids) else 1 if one_based_ids.issubset(response_ids) else 0
        results: list[CriterionResult] = []
        for index, criterion in enumerate(rubric.criteria):
            item = by_id.get(str(index + id_offset), {})
            if not item:
                item = by_id.get(criterion.name, {})
            if not item:
                logger.warning(
                    "LLM criterion item missing criterion_index=%s expected_id=%s criterion_name=%s",
                    index,
                    index + id_offset,
                    criterion.name,
                )
            raw_score = item.get("assigned_score", item.get("score", item.get("awarded_score", 0)))
            try:
                score = min(max(float(raw_score), 0), criterion.max_points)
            except (TypeError, ValueError):
                logger.error(
                    "LLM criterion field validation failed criterion_index=%s field=assigned_score value=%r",
                    index,
                    raw_score,
                    exc_info=True,
                )
                score = 0
            evidence = item.get("evidence", [])
            if isinstance(evidence, str):
                evidence = [evidence]
            if not isinstance(evidence, list):
                logger.error(
                    "LLM criterion field validation failed criterion_index=%s field=evidence value_type=%s",
                    index,
                    type(evidence).__name__,
                )
                evidence = []
            results.append(CriterionResult(
                criterion_id=str(index),
                criterion_name=criterion.name,
                assigned_score=score,
                max_points=criterion.max_points,
                reasoning=str(item.get("reasoning") or "Модель не предоставила обоснование."),
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
            reasoning=str(payload.get("reasoning") or "Проверка происхождения кода с помощью ИИ недоступна."),
            status=str(payload.get("status", "yellow")).lower(),
            confidence=min(max(float(payload.get("confidence", 0)), 0), 1),
        )

    async def _json(self, system: str, user: str) -> dict:
        if not self.is_local and not self.settings.polza_api_key:
            raise RuntimeError("POLZA_API_KEY is required for cloud model evaluation")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user[: self.settings.max_input_chars]}]
        request = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }
        logger.info(
            "LLM request model=%s messages=%s temperature=%s max_tokens=%s json_mode=%s payload=%s",
            self.model,
            len(messages),
            0.2,
            4096,
            True,
            json.dumps(messages, ensure_ascii=False),
        )
        try:
            response = await self.client.chat.completions.create(**request)
        except APIStatusError as err:
            body = err.response.text if err.response is not None else getattr(err, "body", None)
            logger.error("polza.ai request failed status=%s body=%s", err.status_code, str(body)[:4000])
            if err.status_code not in {400, 422}:
                raise
            logger.warning("polza.ai rejected JSON mode; retrying without response_format")
            request.pop("response_format")
            try:
                response = await self.client.chat.completions.create(**request)
            except APIStatusError as retry_err:
                body = retry_err.response.text if retry_err.response is not None else getattr(retry_err, "body", None)
                logger.error("polza.ai fallback request failed status=%s body=%s", retry_err.status_code, str(body)[:4000])
                raise
        except APIError as err:
            logger.error("polza.ai API error body=%s", str(getattr(err, "body", None))[:4000])
            raise
        content = response.choices[0].message.content or "{}"
        print(f"LLM raw output model={response.model or self.model} chars={len(content)}\n{content}", flush=True)
        logger.info(
            "LLM raw output model=%s usage=%s content_len=%d content=%s",
            response.model or self.model,
            response.usage,
            len(content),
            content,
        )
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            logger.exception("LLM response JSON parsing failed content=%s", content[:2000])
            raise
        if not isinstance(payload, dict):
            logger.error("LLM response schema validation failed field=root expected=object got=%s", type(payload).__name__)
            raise ValueError("LLM response must be a JSON object")
        return payload

    def _bounded_submission(self, submission: SubmissionData) -> dict:
        """Produce a JSON-safe, bounded prompt representation of uploaded/repository work."""
        payload = submission.model_dump(mode="json")
        payload["raw_text"] = str(payload.get("raw_text") or "")[: self.settings.max_input_chars]
        payload["file_tree"] = [str(item)[:500] for item in payload.get("file_tree", [])[:500]]
        payload["resolved_links"] = [
            {**item, "content_summary": str(item.get("content_summary") or "")[:1000]}
            for item in payload.get("resolved_links", [])[:100]
            if isinstance(item, dict)
        ]
        return payload


async def grade_submission(llm: LLMService, rubric: TaskRubric, submission: SubmissionData):
    return await llm.grade_criteria(rubric, submission)


def _criterion_max_points(item: object) -> float:
    if not isinstance(item, dict):
        return 0.0
    try:
        return float(item.get("max_points", item.get("max_score", 0)))
    except (TypeError, ValueError):
        return 0.0


def _normalize_criteria(payload: list[object], fallback: list[Criterion]) -> list[dict]:
    normalized: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("title") or "").strip()
        try:
            max_points = float(item.get("max_points", item.get("max_score")))
        except (TypeError, ValueError):
            continue
        if not name or max_points <= 0:
            continue
        normalized.append({
            "name": name,
            "description": str(item.get("description") or ""),
            "min_points": _criterion_min_points(item),
            "max_points": max_points,
        })
    return normalized if len(normalized) >= 2 else [item.model_dump() for item in fallback]


def _criterion_min_points(item: dict) -> float:
    try:
        return max(float(item.get("min_points", item.get("min_score", 0))), 0.0)
    except (TypeError, ValueError):
        return 0.0
