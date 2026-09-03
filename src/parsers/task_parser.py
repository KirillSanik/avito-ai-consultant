import re
from pathlib import Path

import click
import instructor
import pdfplumber
from openai import APIConnectionError, APIError, APITimeoutError, OpenAI
from pydantic import BaseModel, Field

from src.config import AppConfig
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
        api_base = api_base or self.config.api_base
        api_key = api_key or self.config.api_key
        model_name = model_name or self.config.model_name
        client = instructor.from_openai(OpenAI(base_url=api_base, api_key=api_key), mode=instructor.Mode.JSON)
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
        click.echo(f"[2/3] Sending cleaned text to Ollama ({model_name})...")
        request_options = {
            "model": model_name,
            "response_model": ParsedTaskRubric,
            "max_retries": 1,
            "max_tokens": 2600,
            "timeout": 300.0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self.config.ollama_extra_body:
            request_options["extra_body"] = self.config.ollama_extra_body
        try:
            rubric = client.chat.completions.create(**request_options)
        except (APITimeoutError, APIConnectionError, APIError) as exc:
            click.echo(f"Ошибка Ollama: сервис не ответил в течение 5 минут или запрос завершился ошибкой: {exc}", err=True)
            raise click.ClickException("Не удалось получить разбор задания от Ollama.") from exc
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
        pattern = re.compile(
            r"(?P<name>[^\n]+)\n(?:Максимум:\n)?Идеальный результат:\s*"
            r"(?P<description>.*?)(?:Максимум:\n)?0-(?P<max_points>\d+(?:[.,]\d+)?)\s*балл",
            re.DOTALL,
        )
        criteria = []
        for match in pattern.finditer(criteria_section):
            description = re.sub(r"\s+", " ", match.group("description")).strip()
            criteria.append(
                Criterion(
                    name=match.group("name").strip(),
                    description=description,
                    max_points=float(match.group("max_points").replace(",", ".")),
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
