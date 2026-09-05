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
    database_url: str = Field(default="sqlite:///./storage/app.db", description="SQLAlchemy URL (DATABASE_URL).")
    storage_dir: str = Field(default="./storage", description="Корень persistent uploads/reports (STORAGE_DIR).")

    # --- LLM ревьюера (openrouter / ollama) ------------------------------------
    llm_provider: Literal["openrouter", "ollama"] = Field(default="openrouter")
    model_name: str = Field(default="google/gemma-4-31b-it:free")
    api_base: str | None = Field(default=None, description="Переопределение base_url ревьюера.")
    api_key: str | None = Field(default=None, description="Переопределение API-ключа ревьюера.")
    openrouter_api_key: str | None = Field(default=None)
    ollama_fallback_base_url: str = Field(default="http://localhost:11434/v1")
    ollama_fallback_model: str = Field(default="qwen2.5-coder")
    ollama_fallback_api_key: str = Field(default="ollama")

    # --- LLM детектора (локальный OpenAI-совместимый сервер или OpenRouter) ----
    ai_detector_llm_provider: Literal["local", "openrouter"] = Field(
        default="local", description="Провайдер детектора (AI_DETECTOR_LLM_PROVIDER): local | openrouter."
    )
    ai_detector_llm_model: str = Field(
        default="google/gemma-4-31b-it:free",
        description="Модель детектора (AI_DETECTOR_LLM_MODEL).",
    )
    ai_detector_llm_base_url: str | None = Field(default=None, description="Base URL локального LLM-сервера детектора.")
    ai_detector_llm_api_key: str | None = Field(default=None, description="API-ключ LLM-сервера детектора.")

    # --- Общий лимит генерации --------------------------------------------------
    llm_max_tokens: int = Field(
        default=4000, ge=1, description="max_tokens LLM-запросов (LLM_MAX_TOKENS); лимит вывода без усечения."
    )
    llm_disable_thinking: bool = Field(
        default=True,
        description="Отключать reasoning-режим Qwen3 (chat_template_kwargs.enable_thinking=false) — ускоряет ответ.",
    )

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
    def ollama_fallback_chain(self) -> tuple[str, ...]:
        """Local models used only after an account-wide OpenRouter free-tier quota error."""
        return (self.ollama_fallback_model,)

    # --- Детектор: эффективные подключения и цепочка моделей --------------------

    @field_validator("ai_detector_llm_provider")
    @classmethod
    def _validate_detector_provider(cls, value: str) -> str:
        if value not in {"local", "openrouter"}:
            raise ValueError("ai_detector_llm_provider должен быть local или openrouter")
        return value

    @property
    def ai_detector_effective_base_url(self) -> str:
        """Base URL детектора: явное переопределение или OpenRouter/локальный сервер по провайдеру."""
        if self.ai_detector_llm_base_url:
            return self.ai_detector_llm_base_url
        if self.ai_detector_llm_provider == "openrouter":
            return "https://openrouter.ai/api/v1"
        return "http://localhost:11434/v1"

    @property
    def ai_detector_effective_api_key(self) -> str:
        """API-ключ детектора: явное переопределение, иначе OPENROUTER_API_KEY или заглушка."""
        if self.ai_detector_llm_api_key:
            return self.ai_detector_llm_api_key
        if self.ai_detector_llm_provider == "openrouter":
            return self.openrouter_api_key or ""
        return "not-set"

    @property
    def ai_detector_model_chain(self) -> tuple[str, ...]:
        """Цепочка моделей детектора: одна для local; для openrouter — модель + бесплатные резервы."""
        if self.ai_detector_llm_provider != "openrouter":
            return (self.ai_detector_llm_model,)
        return tuple(dict.fromkeys((self.ai_detector_llm_model, *OPENROUTER_FREE_MODELS)))

    @property
    def max_chars(self) -> int | None:
        return 12000 if self.test_mode else None

    @property
    def num_ctx(self) -> int | None:
        return 4096 if self.test_mode else None

    @property
    def ollama_extra_body(self) -> dict[str, Any] | None:
        return {"options": {"num_ctx": self.num_ctx}} if self.num_ctx is not None else None

    @property
    def chat_extra_body(self) -> dict[str, Any] | None:
        """Дополнительное тело chat-запроса: ollama-опции + отключение reasoning Qwen3."""
        body: dict[str, Any] = {}
        if self.ollama_extra_body:
            body.update(self.ollama_extra_body)
        if self.llm_disable_thinking:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        return body or None

    def limit_input_text(self, text: str) -> str:
        """Усекает входной текст до ``max_chars`` в test-режиме; иначе возвращает как есть."""
        if self.max_chars is None:
            return text
        return text[: self.max_chars]


@lru_cache
def get_settings() -> Settings:
    """Синглтон настроек: читает окружение и ``.env`` один раз на процесс."""
    return Settings()
