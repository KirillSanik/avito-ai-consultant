"""Этап (б) разбора условия: LLM-структурирование текста в ``TaskRubric``.

Вынесен в общий слой (ТЗ §5.1, шаг 1): ``Pipeline`` вызывает его строго один
раз на запрос. При сбое LLM-провайдера применяется regex-fallback по разделам
«Критерии оценивания»/«Содержание задания» (поведение прежнего ``TaskParser``);
если и критерии не извлекаются — пробрасывается ошибка LLM-слоя
(``LLMRequestError``/``LLMResilienceError``).
"""

from __future__ import annotations

import logging
import re

import instructor

from common.llm import LLMError, call_with_resilience
from common.models import Criterion, ParsedTaskRubric, TaskRubric
from common.prompts import TASK_PARSE_SYSTEM_PROMPT, TASK_PARSE_USER_PROMPT_TEMPLATE
from common.settings import Settings

logger = logging.getLogger(__name__)

#: Параметры LLM-запроса разбора условия (сохранены из прежней реализации).
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_RETRIES = 1


def clean_and_truncate(content: str, settings: Settings) -> str:
    """Нормализация извлечённого текста: NUL/переносы/пробелы + усечение в test-режиме."""
    cleaned = content.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[\t\f\v ]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = "\n".join(line.strip() for line in cleaned.splitlines()).strip()
    return settings.limit_input_text(cleaned)


async def _llm_parse(
    client: instructor.Instructor, model: str, user_prompt: str, settings: Settings
) -> ParsedTaskRubric:
    """Один запрос instructor (JSON-режим) к указанной модели."""
    request_options: dict[str, object] = {
        "response_model": ParsedTaskRubric,
        "max_retries": DEFAULT_MAX_RETRIES,
        "max_tokens": settings.llm_max_tokens,
        "timeout": DEFAULT_TIMEOUT_SECONDS,
        "messages": [
            {"role": "system", "content": TASK_PARSE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }
    if settings.chat_extra_body:
        request_options["extra_body"] = settings.chat_extra_body
    return await client.chat.completions.create(model=model, **request_options)


async def parse_task_rubric(
    full_text: str, task_id: str, *, client: instructor.Instructor, settings: Settings
) -> TaskRubric:
    """Структурирует текст задания в ``TaskRubric`` (LLM + regex-fallback).

    :raises LLMError: провайдер недоступен после исчерпания повторов/цепочки
        моделей, и критерии не удалось извлечь regex-fallback.
    """
    content = clean_and_truncate(full_text, settings)
    user_prompt = TASK_PARSE_USER_PROMPT_TEMPLATE.format(task_id=task_id, content=content)
    try:
        parsed = await call_with_resilience(
            lambda model: _llm_parse(client, model, user_prompt, settings),
            settings.model_chain,
        )
    except LLMError as exc:
        extracted_criteria = extract_criteria(full_text)
        if not extracted_criteria:
            logger.error("Ошибка LLM-провайдера при разборе условия: %s", exc)
            raise
        logger.warning("LLM-провайдер недоступен, используется regex-fallback по разделам ТЗ: %s", exc)
        parsed = ParsedTaskRubric(
            task_id=task_id,
            title=fallback_title(full_text, task_id),
            description=fallback_description(full_text),
            guidelines=extract_guidelines(full_text),
            criteria=extracted_criteria,
        )
    criteria = extract_criteria(full_text) or parsed.criteria
    guidelines = parsed.guidelines or extract_guidelines(full_text)
    return TaskRubric(
        **parsed.model_dump(exclude={"task_id", "criteria", "guidelines"}),
        task_id=task_id,
        full_instructions=full_text,
        guidelines=guidelines,
        criteria=criteria,
        total_points=sum(criterion.max_points for criterion in criteria),
    )


def extract_criteria(content: str) -> list[Criterion]:
    """Regex-fallback: критерии из раздела «Критерии оценивания» (без LLM)."""
    if "Критерии оценивания" not in content:
        return []
    criteria_section = content.split("Критерии оценивания", 1)[1]
    criteria: list[Criterion] = []
    heading_pattern = re.compile(
        r"(?P<name>[^\n]+)\n(?:Максимум:\s*)?Идеальный результат:\s*",
        re.MULTILINE,
    )
    headings = list(heading_pattern.finditer(criteria_section))
    score_pattern = re.compile(r"0-(?P<max_points>\d+(?:[.,]\d+)?)\s*балл(?:а|ов)?")
    for index, heading in enumerate(headings):
        block_end = headings[index + 1].start() if index + 1 < len(headings) else len(criteria_section)
        block = criteria_section[heading.end():block_end]
        score = score_pattern.search(block)
        if not score:
            continue
        description = score_pattern.sub("", block).strip()
        description = description.split("Чтобы решить это задание", 1)[0].strip()
        description = re.sub(r"\s+", " ", description)
        name = heading.group("name").strip()
        criteria.append(
            Criterion(
                name=name,
                description=description,
                max_points=float(score.group("max_points").replace(",", ".")),
            )
        )
    return criteria


def extract_guidelines(content: str) -> list[str]:
    """Regex-fallback: пошаговые указания из раздела «Содержание задания» (без LLM)."""
    if "Содержание задания:" not in content or "Критерии оценивания" not in content:
        return []
    instructions = content.split("Содержание задания:", 1)[1].split("Критерии оценивания", 1)[0]
    steps = re.split(r"(?=\n[1-9]\d*\.\s)", instructions)
    return [re.sub(r"\s+", " ", step).strip() for step in steps if re.match(r"\s*[1-9]\d*\.\s", step)]


def fallback_title(content: str, task_id: str) -> str:
    """Заголовок без LLM: первая строка с «ДЗ»/«задание», иначе сам task_id."""
    for line in content.splitlines():
        normalized = line.strip()
        if normalized and ("ДЗ" in normalized or "задание" in normalized.lower()):
            return normalized
    return task_id


def fallback_description(content: str) -> str:
    """Описание без LLM: строка после «Цель домашнего задания:»."""
    match = re.search(r"Цель домашнего задания:\s*(.*?)(?:\n|$)", content, re.IGNORECASE)
    return match.group(1).strip() if match else "Описание задания извлечено из исходного документа."
