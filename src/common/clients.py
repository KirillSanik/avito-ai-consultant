"""Фабрики единых LLM-клиентов: конфигурация только из ``common.settings``.

- ``get_llm_client()`` — ``AsyncOpenAI`` для локального OpenAI-совместимого
  сервера детектора (``ai_detector``);
- ``get_openrouter_client()`` — async instructor-клиент (``AsyncOpenAI``,
  JSON-режим) для покритериального ревьюера (``homework_reviewer``).

Оба модуля не создают клиенты самостоятельно (критерий приёмки ТЗ §8).
"""

from __future__ import annotations

import instructor
from openai import AsyncOpenAI

from common.settings import Settings, get_settings

#: Base URL локального LLM-сервера по умолчанию (OpenAI-совместимый, например Ollama).
DEFAULT_DETECTOR_BASE_URL = "http://localhost:11434/v1"


def get_llm_client(settings: Settings | None = None) -> AsyncOpenAI:
    """``AsyncOpenAI`` для детектора: base_url/ключ/модель — из настроек (env/``.env``)."""
    s = settings or get_settings()
    return AsyncOpenAI(
        base_url=s.ai_detector_llm_base_url or DEFAULT_DETECTOR_BASE_URL,
        api_key=s.ai_detector_llm_api_key or "not-set",
    )


def get_openrouter_client(settings: Settings | None = None) -> instructor.Instructor:
    """Async instructor-клиент ревьюера (OpenRouter/Ollama) в JSON-режиме."""
    s = settings or get_settings()
    if s.llm_provider == "openrouter" and not s.openrouter_api_key and not s.api_key:
        raise ValueError("OPENROUTER_API_KEY is required when llm_provider is openrouter")
    return instructor.from_openai(
        AsyncOpenAI(base_url=s.effective_api_base, api_key=s.effective_api_key),
        mode=instructor.Mode.JSON,
    )
