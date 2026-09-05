"""Тесты извлечения текста условия задачи из файла (common.parsers.task_file)."""

from __future__ import annotations

from pathlib import Path

import pytest

from common.parsers.exceptions import TaskFileError
from common.parsers.task_file import SUPPORTED_TASK_EXTENSIONS, extract_task_text


def test_supported_extensions_include_markdown() -> None:
    assert ".md" in SUPPORTED_TASK_EXTENSIONS


def test_extract_task_text_from_markdown(tmp_path: Path) -> None:
    content = "# Задание\n\nНаписать функцию, которая возвращает сумму двух чисел.\n"
    source = tmp_path / "task.md"
    source.write_text(content, encoding="utf-8")

    assert extract_task_text(source) == content


def test_extract_task_text_unsupported_extension(tmp_path: Path) -> None:
    source = tmp_path / "task.xyz"
    source.write_text("data", encoding="utf-8")

    with pytest.raises(TaskFileError):
        extract_task_text(source)