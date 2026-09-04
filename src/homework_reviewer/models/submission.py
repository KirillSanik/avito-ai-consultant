
from pydantic import BaseModel, Field


class LinkInfo(BaseModel):
    url: str = Field(description="Адрес ссылки, найденной в работе студента.")
    status_code: int = Field(description="Код HTTP-ответа или 0, если запрос не был выполнен.")
    is_accessible: bool = Field(description="Доступен ли ресурс для автоматической проверки.")
    content_summary: str = Field(description="Краткое содержание доступной страницы или описание ошибки.")
    is_google_doc: bool = Field(description="Указывает, относится ли ссылка к сервисам Google Docs.")


class ExcelAudit(BaseModel):
    sheet_names: list[str] = Field(default_factory=list, description="Названия листов рабочей книги.")
    total_rows: int = Field(default=0, ge=0, description="Общее число непустых строк на всех листах.")
    has_formulas: bool = Field(default=False, description="Есть ли в книге формулы.")
    hardcoded_count: int = Field(default=0, ge=0, description="Количество заполненных ячеек с введёнными значениями.")
    formula_count: int = Field(default=0, ge=0, description="Количество ячеек с формулами.")


class SubmissionData(BaseModel):
    submission_id: str = Field(description="Идентификатор разбираемой сдачи.")
    task_id: str = Field(description="Идентификатор задания, к которому относится сдача.")
    file_type: str = Field(description="Тип обработанной сдачи: xlsx, docx, pdf или github.")
    file_tree: list[str] = Field(
        default_factory=list, description="Пути файлов, входящих в локальную сдачу или репозиторий."
    )
    raw_text: str = Field(description="Извлечённый текст и табличное представление содержимого файла.")
    tables: list[dict] = Field(default_factory=list, description="Таблицы работы в структурированном виде.")
    excel_audit: ExcelAudit | None = Field(default=None, description="Результат аудита формул Excel, если применимо.")
    resolved_links: list[LinkInfo] = Field(default_factory=list, description="Проверенные внешние ссылки из работы.")
    image_count: int = Field(default=0, ge=0, description="Количество встроенных изображений.")
