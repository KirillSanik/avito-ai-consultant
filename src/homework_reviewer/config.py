import logging
import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("pdfplumber").setLevel(logging.ERROR)

OPENROUTER_FREE_MODELS = (
    "qwen/qwen-2.5-72b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemini-2.0-flash-exp:free",
    "openrouter/free",
)


@dataclass(frozen=True)
class AppConfig:
    test_mode: bool = False
    llm_provider: str = "openrouter"
    model_name: str = "qwen/qwen-2.5-72b-instruct:free"
    model: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    openrouter_api_key: str | None = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY") or None)
    github_token: str | None = field(default_factory=lambda: os.getenv("GITHUB_TOKEN") or None)

    def __post_init__(self) -> None:
        if self.llm_provider not in {"openrouter", "ollama"}:
            raise ValueError("llm_provider должен быть openrouter или ollama")
        if self.model:
            object.__setattr__(self, "model_name", self.model)

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
        if self.max_chars is None:
            return text
        return text[: self.max_chars]
