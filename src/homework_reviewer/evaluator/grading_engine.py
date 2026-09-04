from time import sleep

import click
from instructor.core import IncompleteOutputException, InstructorRetryException
from openai import APIConnectionError, APIError, APITimeoutError

from common.config import AppConfig
from homework_reviewer.evaluator.client_factory import get_instructor_client
from homework_reviewer.models.evaluation import CriterionResult, EvaluationReport
from homework_reviewer.models.rubric import Criterion, TaskRubric
from homework_reviewer.models.submission import SubmissionData
from homework_reviewer.repository.evaluation_repository import EvaluationRepository


class GradingEngine:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig()
        self._has_sent_request = False

    def evaluate_criterion(
        self,
        criterion: Criterion,
        task_rubric: TaskRubric,
        submission_data: SubmissionData,
        config: AppConfig,
    ) -> CriterionResult:
        file_tree = "\n".join(submission_data.file_tree) or (
            f"{submission_data.submission_id}.{submission_data.file_type}"
        )
        raw_text = submission_data.raw_text
        raw_text = config.limit_input_text(raw_text)
        full_instructions = config.limit_input_text(task_rubric.full_instructions)
        excel_audit = submission_data.excel_audit.model_dump_json(indent=2) if submission_data.excel_audit else "Нет"
        resolved_links = "\n".join(link.model_dump_json() for link in submission_data.resolved_links) or "Нет"
        system_prompt = (
            "Ты проверяешь русскоязычную студенческую работу строго по одному критерию с высокой строгостью. "
            "Не учитывай никакие другие критерии и не добавляй требований, которых нет в активном критерии. "
            "Оцени только по представленным данным. Перед начислением каждого балла найди явное доказательство "
            "в тексте, таблицах, ссылках или структуре сдачи и процитируй его в evidence. За частичное выполнение, "
            "пропущенные edge cases, слабое обоснование и поверхностный ответ снижай баллы. Максимум нельзя ставить "
            "по умолчанию: полный балл допустим только при полном, безошибочном выполнении всех требований критерия. "
            "Если все требования критерия исчерпывающе подтверждены, выставь полный балл честно и без занижения. "
            "Поля reasoning и evidence заполняй только на русском языке. Не используй английские слова, кроме "
            "непереводимых названий продуктов, ссылок, форматов файлов и общепринятых аббревиатур. "
            "Баллы должны находиться в диапазоне от 0 до указанного максимума. "
            "Верни только JSON-объект верхнего уровня с ключами criterion_id, criterion_name, "
            "assigned_score, max_points, reasoning и evidence. Не оборачивай объект в ключ "
            "CriterionResult, не используй Markdown и указывай баллы числом. Пример формы: "
            '{"criterion_id":"criterion-1","criterion_name":"название","assigned_score":1.0,'
            '"max_points":1.0,"reasoning":"обоснование","evidence":["факт"]}.'
        )
        user_prompt = (
            f"Задание\n"
            f"Название: {task_rubric.title}\n"
            f"Описание: {task_rubric.description}\n"
            f"Рекомендации: {task_rubric.guidelines}\n"
            f"Ограничения: {task_rubric.constraints.model_dump_json(indent=2)}\n"
            f"Полные инструкции:\n{full_instructions}\n\n"
            f"Активный критерий\n"
            f"Идентификатор: {criterion.name}\n"
            f"Название: {criterion.name}\n"
            f"Максимум баллов: {criterion.max_points}\n"
            f"Описание: {criterion.description}\n\n"
            f"Работа студента\n"
            f"Идентификатор сдачи: {submission_data.submission_id}\n"
            f"Дерево файлов:\n{file_tree}\n\n"
            f"Исходный текст:\n{raw_text}\n\n"
            f"Аудит Excel:\n{excel_audit}\n\n"
            f"Проверенные ссылки:\n{resolved_links}"
        )
        request_options = {
            "max_tokens": 2600,
            "response_model": CriterionResult,
            "max_retries": 1,
            "timeout": 300.0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if config.ollama_extra_body:
            request_options["extra_body"] = config.ollama_extra_body
        last_error: Exception | None = None
        result: CriterionResult | None = None
        for model_name in config.model_chain:
            request_options["model"] = model_name
            for attempt in range(3):
                if attempt:
                    sleep(2 ** attempt)
                try:
                    if self._has_sent_request:
                        sleep(2)
                    self._has_sent_request = True
                    client = get_instructor_client(config)
                    result = client.chat.completions.create(**request_options)
                    break
                except (
                    APITimeoutError,
                    APIConnectionError,
                    APIError,
                    IncompleteOutputException,
                    InstructorRetryException,
                ) as exc:
                    last_error = exc
                    if self._is_model_unavailable(exc) or not self._is_retryable_error(exc):
                        break
                    click.echo(
                        f"Ошибка LLM для модели {model_name}; повтор {attempt + 1}/3.",
                        err=True,
                    )
                    if attempt < 2:
                        sleep(2)
            else:
                result = None
            if result is not None:
                break
            is_fatal_error = (
                last_error is not None
                and not self._is_retryable_error(last_error)
                and not self._is_model_unavailable(last_error)
            )
            if is_fatal_error:
                break
            click.echo(f"Переход к следующей модели после ошибки LLM: {model_name}.", err=True)
        else:
            result = None
        if result is None:
            message = f"Не удалось оценить критерий «{criterion.name}»."
            if last_error is not None:
                click.echo(f"Ошибка LLM-провайдера: {last_error}", err=True)
            raise click.ClickException(message) from last_error
        assigned_score = min(max(float(result.assigned_score), 0.0), float(criterion.max_points))
        return result.model_copy(
            update={
                "criterion_id": criterion.name,
                "criterion_name": criterion.name,
                "assigned_score": assigned_score,
                "max_points": float(criterion.max_points),
            }
        )

    @staticmethod
    def _is_retryable_error(error: Exception) -> bool:
        current: BaseException | None = error
        while current is not None:
            status_code = getattr(current, "status_code", None)
            if status_code in {402, 429} or isinstance(
                current,
                (
                    APIConnectionError,
                    APITimeoutError,
                    IncompleteOutputException,
                    InstructorRetryException,
                ),
            ):
                return True
            current = current.__cause__ or current.__context__
        message = str(error).lower()
        return "in_flight_budget_exhausted" in message or "rate limit" in message or "429" in message

    @staticmethod
    def _is_model_unavailable(error: Exception) -> bool:
        current: BaseException | None = error
        while current is not None:
            if getattr(current, "status_code", None) == 404:
                return True
            current = current.__cause__ or current.__context__
        return "error code: 404" in str(error).lower() or '"code": 404' in str(error).lower()

    def evaluate_submission(
        self,
        rubric: TaskRubric,
        submission_data: SubmissionData,
        config: AppConfig,
    ) -> EvaluationReport:
        criterion_results: list[CriterionResult] = []
        for index, criterion in enumerate(rubric.criteria, start=1):
            click.echo(f"Оценивается критерий {index}/{len(rubric.criteria)}: {criterion.name}")
            result = self.evaluate_criterion(criterion, rubric, submission_data, config)
            criterion_results.append(result.model_copy(update={"criterion_id": f"criterion-{index}"}))
        total_score = sum(result.assigned_score for result in criterion_results)
        max_total_score = sum(result.max_points for result in criterion_results)
        report = EvaluationReport(
            task_id=rubric.task_id,
            submission_id=submission_data.submission_id,
            total_score=total_score,
            max_total_score=max_total_score,
            criterion_results=criterion_results,
            summary_feedback=self._build_summary_feedback(criterion_results, total_score, max_total_score),
        )
        EvaluationRepository().save(report)
        return report

    @staticmethod
    def _build_summary_feedback(
        criterion_results: list[CriterionResult],
        total_score: float,
        max_total_score: float,
    ) -> str:
        if not criterion_results:
            return "В рубрике нет критериев для формирования итоговой обратной связи."
        score_line = f"Итог: {total_score:g} из {max_total_score:g} баллов."
        details = " ".join(
            f"{result.criterion_name}: {result.assigned_score:g}/{result.max_points:g}. {result.reasoning.strip()}"
            for result in criterion_results
        )
        return f"{score_line} {details}".strip()
