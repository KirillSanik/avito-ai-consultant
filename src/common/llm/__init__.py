"""LLM-инфраструктура общего слоя: фабрики клиентов, устойчивость, цепочки моделей.

В этой фазе (3a) вынесен только каталог бесплатных моделей OpenRouter,
используемый ``AppConfig.model_chain`` как резервная цепочка.
"""

from common.llm.models import OPENROUTER_FREE_MODELS

__all__ = ["OPENROUTER_FREE_MODELS"]
