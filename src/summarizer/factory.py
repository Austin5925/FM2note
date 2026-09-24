from __future__ import annotations

from loguru import logger

from src.config import AppConfig
from src.summarizer.base import Summarizer

DEFAULT_DEEPSEEK_MODEL = "deepseek-flash"


def create_summarizer(config: AppConfig) -> Summarizer | None:
    """Select DeepSeek or an OpenAI-compatible summary endpoint.

    Auto prefers the dedicated DeepSeek key.
    """
    provider = config.summary_provider
    if provider == "auto":
        provider = "deepseek" if config.deepseek_api_key else "openai"
    if provider == "none":
        return None
    if provider not in {"deepseek", "openai"}:
        logger.warning("Unsupported summary provider: {}", provider)
        return None

    from src.summarizer.openai_client import OpenAISummarizer

    if provider == "deepseek":
        key = config.deepseek_api_key
        model = config.summary_model or DEFAULT_DEEPSEEK_MODEL
        base_url = "https://api.deepseek.com"
    else:
        key = config.openai_api_key
        model = config.summary_model or "gpt-4o-mini"
        base_url = config.summary_base_url or "https://api.openai.com/v1"
    if not key:
        logger.warning("No API key configured for summary provider {}", provider)
        return None
    logger.info("Summarizer: {} (model={})", provider, model)
    return OpenAISummarizer(
        api_key=key,
        model=model,
        base_url=base_url,
        cooldown=float(config.summary_cooldown),
    )
