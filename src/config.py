from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Subscription:
    """播客订阅配置"""

    name: str
    rss_url: str
    tags: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    """应用全局配置"""

    vault_path: str
    podcast_dir: str = "Podcasts"
    poll_interval_hours: int = 3
    asr_engine: str = "tingwu"
    temp_dir: str = "./data/tmp"
    max_retries: int = 3
    log_level: str = "INFO"
    db_path: str = "./data/state.db"

    # 通义听悟
    alibaba_cloud_access_key_id: str = ""
    alibaba_cloud_access_key_secret: str = ""
    tingwu_app_key: str = ""

    # 阿里云百炼
    dashscope_api_key: str = ""

    # OpenAI Whisper
    openai_api_key: str = ""


class ConfigError(Exception):
    """配置加载错误"""


def load_config(path: str | Path = "config/config.yaml") -> AppConfig:
    """从 YAML 文件加载配置，环境变量覆盖敏感字段。

    Args:
        path: 配置文件路径

    Returns:
        AppConfig 实例

    Raises:
        ConfigError: 配置文件不存在或缺少必填字段
    """
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw:
        raise ConfigError("配置文件为空")

    if "vault_path" not in raw:
        raise ConfigError("缺少必填字段: vault_path")

    # 环境变量覆盖
    vault_path = os.environ.get("OBSIDIAN_VAULT_PATH", raw["vault_path"])

    config = AppConfig(
        vault_path=vault_path,
        podcast_dir=raw.get("podcast_dir", "Podcasts"),
        poll_interval_hours=raw.get("poll_interval_hours", 3),
        asr_engine=raw.get("asr_engine", "tingwu"),
        temp_dir=raw.get("temp_dir", "./data/tmp"),
        max_retries=raw.get("max_retries", 3),
        log_level=os.environ.get("LOG_LEVEL", raw.get("log_level", "INFO")),
        db_path=raw.get("db_path", "./data/state.db"),
        alibaba_cloud_access_key_id=os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", ""),
        alibaba_cloud_access_key_secret=os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", ""),
        tingwu_app_key=os.environ.get("TINGWU_APP_KEY", ""),
        dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
    )

    return config


def load_subscriptions(path: str | Path = "config/subscriptions.yaml") -> list[Subscription]:
    """加载播客订阅列表。

    Args:
        path: 订阅配置文件路径

    Returns:
        Subscription 列表

    Raises:
        ConfigError: 文件不存在或格式错误
    """
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"订阅配置文件不存在: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw or "podcasts" not in raw:
        raise ConfigError("订阅配置文件格式错误: 缺少 podcasts 字段")

    subscriptions = []
    for item in raw["podcasts"]:
        if "name" not in item or "rss_url" not in item:
            raise ConfigError(f"订阅条目缺少必填字段 (name/rss_url): {item}")
        subscriptions.append(
            Subscription(
                name=item["name"],
                rss_url=item["rss_url"],
                tags=item.get("tags", []),
            )
        )

    return subscriptions
