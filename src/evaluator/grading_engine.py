import click
import instructor
from openai import APIConnectionError, APIError, APITimeoutError, OpenAI

from src.config import AppConfig
from src.models.evaluation import CriterionResult, EvaluationReport
from src.models.rubric import Criterion, TaskRubric
from src.models.submission import SubmissionData
from src.repository.evaluation_repository import EvaluationRepository


class GradingEngine:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig()

    def evaluate_criterion(
        self,
        criterion: Criterion,
        task_rubric: TaskRubric,
        submission_data: SubmissionData,
        config: AppConfig,
    ) -> CriterionResult:
        client = instructor.from_openai(OpenAI(base_url=config.api_base, api_key=config.api_key), mode=instructor.Mode.JSON)
        file_tree = "\n".join(submission_data.file_tree) or f"{submission_data.submission_id}.{submission_data.file_type}"
        raw_text = submission_data.raw_text
        raw_text = config.limit_input_text(raw_text)
        full_instructions = config.limit_input_text(task_rubric.full_instructions)
        excel_audit = submission_data.excel_audit.model_dump_json(indent=2) if submission_data.excel_audit else "Нет"
        resolved_links = "\n".join(link.model_dump_json() for link in submission_data.resolved_links) or "Нет"
        system_prompt = (
            "Ты проверяешь русскоязычную студенческую работу строго по одному критерию. "
            "Не учитывай никакие другие критерии и не добавляй требований, которых нет в активном критерии. "
            "Оцени только по представленным данным, приведи конкретные доказательства из работы. "
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
            "model": config.model_name,
            "max_tokens": 800,
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
        try:
            result = client.chat.completions.create(**request_options)
        except (APITimeoutError, APIConnectionError, APIError) as exc:
            click.echo(f"Ошибка Ollama: сервис не ответил в течение 5 минут или запрос завершился ошибкой: {exc}", err=True)
            raise click.ClickException(f"Не удалось оценить критерий «{criterion.name}».") from exc
        assigned_score = min(max(float(result.assigned_score), 0.0), float(criterion.max_points))
        return result.model_copy(
            update={
                "criterion_id": criterion.name,
                "criterion_name": criterion.name,
                "assigned_score": assigned_score,
                "max_points": float(criterion.max_points),
            }
        )

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
