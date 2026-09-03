import logging
import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv


load_dotenv()

logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("pdfplumber").setLevel(logging.ERROR)


@dataclass(frozen=True)
class AppConfig:
    test_mode: bool = False
    model: str | None = None
    api_base: str = "http://localhost:11434/v1"
    api_key: str = "ollama"
    github_token: str | None = field(default_factory=lambda: os.getenv("GITHUB_TOKEN") or None)

    @property
    def model_name(self) -> str:
        if self.model:
            return self.model
        return "qwen2.5:1.5b" if self.test_mode else "qwen2.5:7b"

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
