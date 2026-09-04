"""Единая типизированная конфигурация приложения (pydantic-settings, чтение ``.env``).

Единственная точка доступа к переменным окружения для обеих фич:
``LLMJudge``, клонирование репозитория, парсеры и API читают окружение
только через этот модуль (конституция: DRY, strict typing).

Поведение перенесено из бывшего ``common/config.py`` (``AppConfig``):
выбор модели, резервная цепочка ``model_chain``, ``limit_input_text``,
``effective_api_base``/``effective_api_key``, ``ollama_extra_body``,
приоритет токена git (``AI_DETECTOR_GIT_TOKEN`` > ``GITHUB_TOKEN``).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from common.llm import OPENROUTER_FREE_MODELS

logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("pdfplumber").setLevel(logging.ERROR)


class Settings(BaseSettings):
    """Типизированные настройки: API, LLM-провайдеры, git-токены, режим тестирования."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- API (FastAPI/uvicorn) -------------------------------------------------
    app_host: str = Field(default="127.0.0.1", description="Хост запуска uvicorn.")
    app_port: int = Field(default=8000, ge=1, le=65535, description="Порт запуска uvicorn.")
    app_workers: int = Field(default=1, ge=1, description="Число workers uvicorn.")

    # --- LLM ревьюера (openrouter / ollama) ------------------------------------
    llm_provider: Literal["openrouter", "ollama"] = Field(default="openrouter")
    model_name: str = Field(default="qwen/qwen-2.5-72b-instruct:free")
    api_base: str | None = Field(default=None, description="Переопределение base_url ревьюера.")
    api_key: str | None = Field(default=None, description="Переопределение API-ключа ревьюера.")
    openrouter_api_key: str | None = Field(default=None)

    # --- LLM детектора (локальный OpenAI-совместимый сервер) -------------------
    ai_detector_llm_model: str = Field(default="local-model", description="Модель детектора (AI_DETECTOR_LLM_MODEL).")
    ai_detector_llm_base_url: str | None = Field(default=None, description="Base URL локального LLM-сервера детектора.")
    ai_detector_llm_api_key: str | None = Field(default=None, description="API-ключ локального LLM-сервера детектора.")

    # --- Git-токены приватных репозиториев -------------------------------------
    github_token: str | None = Field(default=None)
    ai_detector_git_token: str | None = Field(
        default=None, description="Приоритет над GITHUB_TOKEN (AI_DETECTOR_GIT_TOKEN)."
    )

    # --- Прочее ----------------------------------------------------------------
    test_mode: bool = Field(default=False, description="Режим тестирования: усечение входа и num_ctx.")

    @field_validator("llm_provider")
    @classmethod
    def _validate_provider(cls, value: str) -> str:
        if value not in {"openrouter", "ollama"}:
            raise ValueError("llm_provider должен быть openrouter или ollama")
        return value

    # --- Сохранённое поведение AppConfig ---------------------------------------

    @property
    def git_token(self) -> str | None:
        """Токен для git-доступа: ``AI_DETECTOR_GIT_TOKEN`` имеет приоритет над ``GITHUB_TOKEN``."""
        return self.ai_detector_git_token or self.github_token

    @property
    def effective_api_base(self) -> str:
        if self.api_base:
            return self.api_base
        return "https://openrouter.ai/api/v1" if self.llm_provider == "openrouter" else "http://localhost:11434/v1"

    @property
    def effective_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        if self.llm_provider == "openrouter":
            return self.openrouter_api_key or ""
        return "ollama"

    @property
    def model_chain(self) -> tuple[str, ...]:
        """Модель по умолчанию + резервная цепочка бесплатных моделей OpenRouter (без дублей)."""
        if self.llm_provider != "openrouter":
            return (self.model_name,)
        return tuple(dict.fromkeys((self.model_name, *OPENROUTER_FREE_MODELS)))

    @property
    def max_chars(self) -> int | None:
        return 12000 if self.test_mode else None

    @property
    def num_ctx(self) -> int | None:
        return 4096 if self.test_mode else None

    @property
    def ollama_extra_body(self) -> dict[str, Any] | None:
        return {"options": {"num_ctx": self.num_ctx}} if self.num_ctx is not None else None

    def limit_input_text(self, text: str) -> str:
        """Усекает входной текст до ``max_chars`` в test-режиме; иначе возвращает как есть."""
        if self.max_chars is None:
            return text
        return text[: self.max_chars]


@lru_cache
def get_settings() -> Settings:
    """Синглтон настроек: читает окружение и ``.env`` один раз на процесс."""
    return Settings()
