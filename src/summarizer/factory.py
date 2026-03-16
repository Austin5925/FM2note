from __future__ import annotations

from loguru import logger

from src.config import AppConfig
from src.summarizer.base import Summarizer


def create_summarizer(config: AppConfig) -> Summarizer | None:
    """Create a summarizer based on config.

    Selection logic:
    - summary_provider="poe"    → PoeSummarizer (requires POE_API_KEY)
    - summary_provider="openai" → OpenAISummarizer (requires OPENAI_API_KEY)
    - summary_provider="none"   → None
    - summary_provider="auto"   → auto-detect based on available API keys

    Returns:
        Summarizer instance or None if no provider configured.
    """
    provider = config.summary_provider

    if provider == "none":
        logger.info("Summary provider set to 'none', skipping AI summaries")
        return None

    if provider == "poe":
        if not config.poe_api_key:
            logger.warning("summary_provider=poe but POE_API_KEY not set, skipping")
            return None
        return _create_poe(config)

    if provider == "openai":
        if not config.openai_api_key:
            logger.warning("summary_provider=openai but OPENAI_API_KEY not set, skipping")
            return None
        return _create_openai(config)

    # Auto-detect: try available keys
    if config.poe_api_key:
        return _create_poe(config)
    if config.openai_api_key:
        return _create_openai(config)

    logger.info("No summary API key configured, skipping AI summaries")
    return None


def _create_poe(config: AppConfig) -> Summarizer:
    from src.summarizer.poe_client import PoeSummarizer

    logger.info(
        "Summarizer: Poe (model={}, cooldown={}s)",
        config.summary_model or "GPT-5.4",
        config.summary_cooldown,
    )
    return PoeSummarizer(
        api_key=config.poe_api_key,
        model=config.summary_model or "GPT-5.4",
        cooldown=float(config.summary_cooldown),
    )


def _create_openai(config: AppConfig) -> Summarizer:
    from src.summarizer.openai_client import OpenAISummarizer

    model = config.summary_model or "gpt-4o-mini"
    base_url = config.summary_base_url or "https://api.openai.com/v1"
    logger.info(
        "Summarizer: OpenAI-compatible (model={}, base_url={}, cooldown={}s)",
        model,
        base_url,
        config.summary_cooldown,
    )
    return OpenAISummarizer(
        api_key=config.openai_api_key,
        model=model,
        base_url=base_url,
        cooldown=float(config.summary_cooldown),
    )
