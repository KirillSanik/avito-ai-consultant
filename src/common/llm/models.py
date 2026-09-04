"""Каталоги моделей, общие для обеих фич."""

#: Бесплатные модели OpenRouter — резервная цепочка ``AppConfig.model_chain``.
OPENROUTER_FREE_MODELS: tuple[str, ...] = (
    "qwen/qwen-2.5-72b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemini-2.0-flash-exp:free",
    "openrouter/free",
)
