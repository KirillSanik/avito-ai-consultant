"""Юнит-тесты LocalCodeAggregator: фильтрация, маркеры, полное содержимое без усечения, параллелизм (FR-004, FR-005, FR-014).

Файлы создаются реально во временном каталоге (tmp_path); aiofiles подменяется
для замера пиковой параллельности чтения (лимит 20).
"""

from __future__ import annotations

import asyncio
import logging
import types
from pathlib import Path

import pytest

import ai_detector.code_aggregator as code_aggregator_module
from ai_detector.code_aggregator import LocalCodeAggregator
from ai_detector.exceptions import CodeAggregationError


def write(root: Path, rel: str, content: str = "x") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


async def test_whitelist_and_blacklist_dirs(tmp_path: Path) -> None:
    """Белый список расширений + чёрный список директорий (FR-005)."""
    write(tmp_path, "src/main.py", "print('hi')")
    write(tmp_path, "README.md", "# домашка")
    write(tmp_path, "sub/dir/ok.go", "package main")
    write(tmp_path, "notes.txt", "не поддерживается")
    write(tmp_path, "venv/lib/site.py", "код виртуального окружения")
    write(tmp_path, "node_modules/pkg/index.js", "js-зависимость")
    write(tmp_path, "__pycache__/mod.pyc", "байт-код")
    write(tmp_path, ".git/config", "[core]")
    write(tmp_path, ".idea/idea.xml", "<xml/>")

    result = await LocalCodeAggregator().aggregate(tmp_path)

    assert "--- FILE: src/main.py ---" in result
    assert "--- FILE: README.md ---" in result
    assert "--- FILE: sub/dir/ok.go ---" in result
    assert "--- FILE: notes.txt ---" not in result
    assert "venv/lib/site.py" not in result
    assert "node_modules/pkg/index.js" not in result
    assert "__pycache__/mod.pyc" not in result
    assert ".git/config" not in result
    assert ".idea/idea.xml" not in result


async def test_markers_and_full_content_without_truncation(tmp_path: Path) -> None:
    """Маркеры разделителей и ПОЛНОЕ содержимое файлов, без усечения (FR-004)."""
    content = "".join(f"def f{i}(x):\n    return x + {i}\n" for i in range(300))
    write(tmp_path, "big.py", content)

    result = await LocalCodeAggregator().aggregate(tmp_path)

    assert result.startswith("--- FILE: big.py ---\n")
    assert content in result  # всё содержимое, ни одной строки не потеряно
    assert result.rstrip("\n").endswith("--- END FILE ---")


async def test_no_supported_files_raises(tmp_path: Path) -> None:
    """Только неподдерживаемые файлы → CodeAggregationError."""
    write(tmp_path, "photo.png", "img")
    write(tmp_path, "data.txt", "текст")
    with pytest.raises(CodeAggregationError, match="no supported source files"):
        await LocalCodeAggregator().aggregate(tmp_path)


async def test_empty_dir_raises(tmp_path: Path) -> None:
    """Пустой каталог → CodeAggregationError."""
    with pytest.raises(CodeAggregationError, match="no supported source files"):
        await LocalCodeAggregator().aggregate(tmp_path)


async def test_reads_limited_by_semaphore_of_20(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """FR-014: пиковая параллельность чтения == 20 при 30 файлах."""
    for index in range(30):
        write(tmp_path, f"f{index:02d}.py", f"код {index}")

    peak = 0
    active = 0

    class FakeFile:
        def __init__(self, content: str) -> None:
            self._content = content

        async def read(self) -> str:
            return self._content

        async def __aenter__(self) -> FakeFile:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

    class FakeFileOpen:
        def __init__(self, content: str) -> None:
            self._content = content

        async def __aenter__(self) -> FakeFile:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)  # дать другим задачам успеть начать чтение
            return FakeFile(self._content)

        async def __aexit__(self, *exc: object) -> bool:
            nonlocal active
            active -= 1
            return False

    def fake_open(path: Path, *args: object, **kwargs: object) -> FakeFileOpen:
        return FakeFileOpen(path.read_text(encoding="utf-8"))

    monkeypatch.setattr(code_aggregator_module, "aiofiles", types.SimpleNamespace(open=fake_open))

    result = await LocalCodeAggregator().aggregate(tmp_path)

    assert peak == 20
    assert all(f"--- FILE: f{index:02d}.py ---" in result for index in range(30))


async def test_non_utf8_file_skipped_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """FR-013: не-UTF8 (бинарный) файл с поддерживаемым расширением — пропуск с warning, без срыва."""
    write(tmp_path, "ok.py", "print('hi')")
    (tmp_path / "binary.py").write_bytes(b"\xff\xfe\x00\x01\x89PNG not-utf8")

    with caplog.at_level(logging.WARNING, logger="ai_detector.code_aggregator"):
        result = await LocalCodeAggregator().aggregate(tmp_path)

    assert "--- FILE: ok.py ---" in result
    assert "binary.py" not in result
    assert any("не является текстом UTF-8" in record.message for record in caplog.records)


async def test_only_non_utf8_files_raises_code_aggregation_error(tmp_path: Path) -> None:
    """Все поддерживаемые файлы бинарные → чёткая доменная ошибка, а не пустой/мусорный результат (FR-013)."""
    (tmp_path / "binary.py").write_bytes(b"\xff\xfe\x00\x01")
    with pytest.raises(CodeAggregationError, match="не удалось прочитать"):
        await LocalCodeAggregator().aggregate(tmp_path)


async def test_read_oserror_wrapped_in_code_aggregation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-013: OSError при чтении файла → CodeAggregationError (русское сообщение), а не «сырой» OSError."""
    write(tmp_path, "broken.py", "код")

    def failing_open(*_args: object, **_kwargs: object) -> types.SimpleNamespace:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(code_aggregator_module, "aiofiles", types.SimpleNamespace(open=failing_open))
    with pytest.raises(CodeAggregationError) as exc_info:
        await LocalCodeAggregator().aggregate(tmp_path)
    assert "Не удалось прочитать файл" in str(exc_info.value)
