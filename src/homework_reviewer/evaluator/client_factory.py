import instructor
from openai import OpenAI

from common.config import AppConfig


def get_instructor_client(config: AppConfig):
    if config.llm_provider == "openrouter" and not config.openrouter_api_key and not config.api_key:
        raise ValueError("OPENROUTER_API_KEY is required when llm_provider is openrouter")
    return instructor.from_openai(
        OpenAI(base_url=config.effective_api_base, api_key=config.effective_api_key),
        mode=instructor.Mode.JSON,
    )
