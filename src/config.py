from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from loguru import logger

# Personal default for this fork — used as the placeholder in the Web UI and
# the fallback in `fm2note init` when no Obsidian vault auto-detection succeeds.
# Living in one place so we can change it in one place.
DEFAULT_VAULT_PATH = (
    "/Users/somebody/Library/Mobile Documents/iCloud~md~obsidian/Documents/zhen/10_Podcasts"
)


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


# Config fields that USED to be honored from env (pre-v1.4.12) but are now
# yaml-only. We still detect them on startup so we can tell the user their
# stale .env entry is being ignored, instead of silently doing the right thing
# (which is what made the OBSIDIAN_VAULT_PATH bug so hard to spot).
_LEGACY_YAML_ENV_VARS = (
    "OBSIDIAN_VAULT_PATH",
    "LOG_LEVEL",
    "SUMMARY_PROVIDER",
    "SUMMARY_MODEL",
    "SUMMARY_COOLDOWN",
    "SUMMARY_BASE_URL",
)

# Module-level flag so the stale-env warning fires once per process even if
# load_config() is invoked on every HTTP request (which it is — see
# src/web/routes/settings_api.py and src/web/routes/health.py). Without this
# the user's log would get a fresh warning line for every page load.
_legacy_env_warning_emitted = False


def load_config(path: str | Path = "config/config.yaml") -> AppConfig:
    """Load config from YAML.

    Non-sensitive fields (vault_path, podcast_dir, asr_engine, log_level,
    summary_*, etc.) come ONLY from ``config.yaml`` — the Web UI's single
    editable surface. Sensitive credentials (DashScope/Poe/OpenAI keys,
    Aliyun AK/SK, TingWu App ID) come ONLY from environment variables (.env)
    because they shouldn't live in a file that gets synced or committed.

    There is no mixed read path anymore. Pre-v1.4.12 several non-sensitive
    fields had ``env > yaml`` precedence, which let a stale ``.env`` silently
    shadow Web UI saves (the OBSIDIAN_VAULT_PATH regression).

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

    # Warn (don't fail) when a legacy env var is still set, so the user knows
    # their .env entry isn't doing what they think. Guarded by a module-level
    # flag because load_config() runs per-request in the web layer.
    global _legacy_env_warning_emitted
    if not _legacy_env_warning_emitted:
        stale = [name for name in _LEGACY_YAML_ENV_VARS if os.environ.get(name)]
        if stale:
            logger.warning(
                "以下环境变量自 v1.4.12 起不再生效（已迁到 config.yaml）：{}。"
                "可从 .env 删除以避免混淆。",
                ", ".join(stale),
            )
        _legacy_env_warning_emitted = True

    config = AppConfig(
        vault_path=raw["vault_path"],
        podcast_dir=raw.get("podcast_dir", "Podcasts"),
        poll_interval_hours=raw.get("poll_interval_hours", 3),
        asr_engine=raw.get("asr_engine", "funasr"),
        temp_dir=raw.get("temp_dir", "./data/tmp"),
        max_retries=raw.get("max_retries", 3),
        log_level=raw.get("log_level", "INFO"),
        db_path=raw.get("db_path", "./data/state.db"),
        # Sensitive — env-only
        dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        tingwu_app_id=os.environ.get("TINGWU_APP_ID", ""),
        poe_api_key=os.environ.get("POE_API_KEY", ""),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        # Non-sensitive — yaml-only (formerly env > yaml, see top of function)
        summary_provider=raw.get("summary_provider", "auto"),
        summary_model=raw.get("summary_model", ""),
        summary_cooldown=int(raw.get("summary_cooldown", 60)),
        summary_base_url=raw.get("summary_base_url", ""),
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

    if not raw or "podcasts" not in raw or not raw["podcasts"]:
        raise ConfigError(
            f"No podcasts configured in {path}. "
            "Edit the file and add at least one podcast entry under 'podcasts:'."
        )

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
