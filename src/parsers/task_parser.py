import re
from pathlib import Path

import click
from instructor.core import InstructorRetryException
import pdfplumber
from openai import APIConnectionError, APIError, APITimeoutError
from pydantic import BaseModel, Field

from src.config import AppConfig
from src.evaluator.client_factory import get_instructor_client
from src.models.rubric import Constraints, Criterion, TaskRubric


class ParsedTaskRubric(BaseModel):
    task_id: str
    title: str
    description: str
    guidelines: list[str] = Field(default_factory=list)
    criteria: list[Criterion] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)


class TaskParser:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig()

    def extract_pdf_content(self, pdf_path: str) -> str:
        source = Path(pdf_path)
        if not source.is_file():
            raise FileNotFoundError(f"PDF-файл не найден: {pdf_path}")

        sections: list[str] = []
        with pdfplumber.open(source) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                page_parts = [f"## Страница {page_number}"]
                text = page.extract_text()
                if text:
                    page_parts.append(text)
                for table_number, table in enumerate(page.extract_tables(), start=1):
                    markdown = self._table_to_markdown(table)
                    if markdown:
                        page_parts.append(f"### Таблица {table_number}\n{markdown}")
                sections.append("\n\n".join(page_parts))
        return "\n\n".join(sections)

    def parse_task(
        self,
        pdf_path: str,
        task_id: str,
        api_base: str | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
    ) -> TaskRubric:
        click.echo("[1/3] Extracting text from PDF...")
        full_instructions = self.extract_pdf_content(pdf_path)
        content = self._clean_and_truncate(full_instructions)
        config = AppConfig(
            test_mode=self.config.test_mode,
            llm_provider=self.config.llm_provider,
            model_name=model_name or self.config.model_name,
            api_base=api_base or self.config.api_base,
            api_key=api_key or self.config.api_key,
            openrouter_api_key=self.config.openrouter_api_key,
        )
        try:
            client = get_instructor_client(config)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        system_prompt = (
            "Ты эксперт по анализу учебных заданий на русском языке. Извлеки требования "
            "из текста PDF и заполни предложенную схему. Сохраняй исходный смысл на русском. "
            "Включи все критерии и диапазоны баллов. Поле guidelines заполни последовательными "
            "пошаговыми инструкциями по выполнению задания из документа. В constraints отдельно "
            "перенеси технические требования, требования к оформлению (включая объём, шрифты и "
            "структуру), требования к формату и способу сдачи, а также запрещённые действия. Если значение "
            "отсутствует, используй пустой список или ноль; не выдумывай требования. Поле "
            "constraints обязательно верни объектом с ключами technical_requirements, "
            "formatting_requirements, submission_requirements, prohibited_actions и "
            "additional_requirements, каждый из которых содержит список строк. Формулируй поля кратко, "
            "без повторения исходного документа."
        )
        user_prompt = f"Идентификатор задания: {task_id}\n\nТекст задания:\n{content}"
        click.echo(f"[2/3] Sending cleaned text to {config.llm_provider} ({config.model_name})...")
        request_options = {
            "model": config.model_name,
            "response_model": ParsedTaskRubric,
            "max_retries": 1,
            "max_tokens": 2600,
            "timeout": 300.0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if config.ollama_extra_body:
            request_options["extra_body"] = config.ollama_extra_body
        try:
            rubric = client.chat.completions.create(**request_options)
        except (APITimeoutError, APIConnectionError, APIError, InstructorRetryException) as exc:
            extracted_criteria = self._extract_criteria(full_instructions)
            if not extracted_criteria:
                click.echo(f"Ошибка LLM-провайдера: сервис не ответил в течение 5 минут или запрос завершился ошибкой: {exc}", err=True)
                raise click.ClickException("Не удалось получить разбор задания.") from exc
            rubric = ParsedTaskRubric(
                task_id=task_id,
                title=self._fallback_title(full_instructions, task_id),
                description=self._fallback_description(full_instructions),
                guidelines=self._extract_guidelines(full_instructions),
                criteria=extracted_criteria,
            )
        extracted_criteria = self._extract_criteria(full_instructions)
        criteria = extracted_criteria or rubric.criteria
        guidelines = rubric.guidelines or self._extract_guidelines(full_instructions)
        rubric = TaskRubric(
            **rubric.model_dump(exclude={"task_id", "criteria", "guidelines"}),
            task_id=task_id,
            full_instructions=full_instructions,
            guidelines=guidelines,
            criteria=criteria,
            total_points=sum(criterion.max_points for criterion in criteria),
        )
        click.echo("[3/3] Task rubric parsed and created.")
        return rubric

    def _clean_and_truncate(self, content: str) -> str:
        cleaned = content.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
        cleaned = re.sub(r"[\t\f\v ]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = "\n".join(line.strip() for line in cleaned.splitlines()).strip()
        return self.config.limit_input_text(cleaned)

    @staticmethod
    def _extract_criteria(content: str) -> list[Criterion]:
        if "Критерии оценивания" not in content:
            return []
        criteria_section = content.split("Критерии оценивания", 1)[1]
        criteria = []
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

    @staticmethod
    def _extract_guidelines(content: str) -> list[str]:
        if "Содержание задания:" not in content or "Критерии оценивания" not in content:
            return []
        instructions = content.split("Содержание задания:", 1)[1].split("Критерии оценивания", 1)[0]
        steps = re.split(r"(?=\n[1-9]\d*\.\s)", instructions)
        return [re.sub(r"\s+", " ", step).strip() for step in steps if re.match(r"\s*[1-9]\d*\.\s", step)]

    @staticmethod
    def _fallback_title(content: str, task_id: str) -> str:
        for line in content.splitlines():
            normalized = line.strip()
            if normalized and ("ДЗ" in normalized or "задание" in normalized.lower()):
                return normalized
        return task_id

    @staticmethod
    def _fallback_description(content: str) -> str:
        match = re.search(r"Цель домашнего задания:\s*(.*?)(?:\n|$)", content, re.IGNORECASE)
        return match.group(1).strip() if match else "Описание задания извлечено из исходного документа."

    @staticmethod
    def _table_to_markdown(table: list[list[str | None]]) -> str:
        rows = [[(cell or "").replace("|", "\\|").replace("\n", " ").strip() for cell in row] for row in table if row]
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        normalized_rows = [row + [""] * (width - len(row)) for row in rows]
        header = normalized_rows[0]
        separator = ["-" * 3] * width
        body = normalized_rows[1:]
        return "\n".join([self_row(header), self_row(separator), *[self_row(row) for row in body]])


def self_row(row: list[str]) -> str:
    return "| " + " | ".join(row) + " |"
