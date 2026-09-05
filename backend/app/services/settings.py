import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PipelineSettings:
    storage_dir: Path
    llm_provider: str
    model_name: str
    polza_api_key: str | None
    polza_base_url: str
    ollama_base_url: str
    ollama_model: str
    github_token: str | None
    max_input_chars: int

    @classmethod
    def from_environment(cls) -> "PipelineSettings":
        return cls(
            storage_dir=Path(os.getenv("STORAGE_DIR", "./storage")),
            llm_provider=os.getenv("LLM_PROVIDER", "cloud"),
            model_name=os.getenv("LLM_MODEL", "qwen/qwen3.8-flash"),
            polza_api_key=os.getenv("POLZA_API_KEY"),
            polza_base_url=os.getenv("POLZA_BASE_URL", "https://polza.ai/api/v1"),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5-coder"),
            github_token=os.getenv("GITHUB_TOKEN"),
            max_input_chars=int(os.getenv("LLM_MAX_INPUT_CHARS", "60000")),
        )
