from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Subscription:
    """Podcast subscription entry."""

    name: str
    rss_url: str
    tags: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    """Application configuration."""

    vault_path: str
    podcast_dir: str = "Podcasts"
    poll_interval_hours: int = 3
    asr_engine: str = "funasr"
    temp_dir: str = "./data/tmp"
    max_retries: int = 3
    log_level: str = "INFO"
    db_path: str = "./data/state.db"

    # DashScope API Key (shared by TingWu / FunASR / Bailian)
    dashscope_api_key: str = ""

    # TingWu AppId
    tingwu_app_id: str = ""

    # AI summary provider: auto | poe | openai | none
    summary_provider: str = "auto"
    summary_model: str = ""  # provider default if empty
    summary_cooldown: int = 60
    summary_base_url: str = ""  # OpenAI-compatible endpoint (optional)

    # Poe API (AI summaries)
    poe_api_key: str = ""

    # OpenAI (Whisper API + summaries)
    openai_api_key: str = ""

    # Custom template path (relative to project root)
    template_path: str = ""


class ConfigError(Exception):
    """Configuration loading error."""


def _hint_example_file(path: Path) -> str:
    """Return a hint message if an .example counterpart exists."""
    example = path.with_suffix(".example.yaml") if path.suffix == ".yaml" else None
    if example and example.exists():
        return f"\n  Hint: copy the example file first:\n  cp {example} {path}"
    return ""


def load_config(path: str | Path = "config/config.yaml") -> AppConfig:
    """Load config from YAML, with env var overrides for sensitive fields.

    Args:
        path: Path to config YAML file.

    Returns:
        AppConfig instance.

    Raises:
        ConfigError: If config file is missing, empty, or invalid.
    """
    path = Path(path)
    if not path.exists():
        hint = _hint_example_file(path)
        raise ConfigError(f"Config file not found: {path}{hint}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw:
        raise ConfigError(f"Config file is empty: {path}")

    if "vault_path" not in raw:
        raise ConfigError("Missing required field in config: vault_path")

    # Environment variable overrides
    vault_path = os.environ.get("OBSIDIAN_VAULT_PATH", raw["vault_path"])

    config = AppConfig(
        vault_path=vault_path,
        podcast_dir=raw.get("podcast_dir", "Podcasts"),
        poll_interval_hours=raw.get("poll_interval_hours", 3),
        asr_engine=raw.get("asr_engine", "funasr"),
        temp_dir=raw.get("temp_dir", "./data/tmp"),
        max_retries=raw.get("max_retries", 3),
        log_level=os.environ.get("LOG_LEVEL", raw.get("log_level", "INFO")),
        db_path=raw.get("db_path", "./data/state.db"),
        dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        tingwu_app_id=os.environ.get("TINGWU_APP_ID", ""),
        summary_provider=os.environ.get("SUMMARY_PROVIDER", raw.get("summary_provider", "auto")),
        summary_model=os.environ.get("SUMMARY_MODEL", raw.get("summary_model", "")),
        summary_cooldown=int(os.environ.get("SUMMARY_COOLDOWN", raw.get("summary_cooldown", 60))),
        summary_base_url=os.environ.get("SUMMARY_BASE_URL", raw.get("summary_base_url", "")),
        poe_api_key=os.environ.get("POE_API_KEY", ""),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        template_path=raw.get("template_path", ""),
    )

    return config


def load_subscriptions(path: str | Path = "config/subscriptions.yaml") -> list[Subscription]:
    """Load podcast subscription list.

    Args:
        path: Path to subscriptions YAML file.

    Returns:
        List of Subscription objects.

    Raises:
        ConfigError: If file is missing or malformed.
    """
    path = Path(path)
    if not path.exists():
        hint = _hint_example_file(path)
        raise ConfigError(f"Subscriptions file not found: {path}{hint}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw or "podcasts" not in raw:
        raise ConfigError(f"Invalid subscriptions file (missing 'podcasts' key): {path}")

    subscriptions = []
    for item in raw["podcasts"]:
        if "name" not in item or "rss_url" not in item:
            raise ConfigError(f"Subscription entry missing required fields (name/rss_url): {item}")
        subscriptions.append(
            Subscription(
                name=item["name"],
                rss_url=item["rss_url"],
                tags=item.get("tags", []),
            )
        )

    return subscriptions
