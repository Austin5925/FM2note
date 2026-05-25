from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from loguru import logger

from src.config import DEFAULT_VAULT_PATH, load_config
from src.web.paths import CONFIG_PATH, ENV_PATH
from src.web.services import locks
from src.web.services.env_writer import build_env_text, stage_atomic_write
from src.web.services.yaml_writer import dump_yaml_text, load_yaml

router = APIRouter(prefix="/api")


# Map UI setting names → env var names. Sensitive credentials only.
# Non-sensitive fields (vault_path, summary_provider, etc.) go to YAML so a
# stale .env can't silently shadow Web UI edits — see v1.4.12 changelog.
_ENV_KEY_MAP = {
    "dashscope_api_key": "DASHSCOPE_API_KEY",
    "poe_api_key": "POE_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "tingwu_app_id": "TINGWU_APP_ID",
    "aliyun_access_key_id": "ALIYUN_ACCESS_KEY_ID",
    "aliyun_access_key_secret": "ALIYUN_ACCESS_KEY_SECRET",
}

_YAML_FIELDS = {
    "vault_path",
    "podcast_dir",
    "asr_engine",
    "summary_provider",
    "summary_model",
    "summary_cooldown",
    "summary_base_url",
    "log_level",
}


def _clean_path_input(value: str) -> str:
    """Normalize a user-typed path: trim whitespace and stripped wrapping quotes.

    Users sometimes paste paths copied from a shell command or doc that include
    enclosing ``'…'`` or ``"…"``. Those quotes are not part of the path —
    silently stripping them avoids a confusing ``does not exist`` error.
    """
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ("'", '"'):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "****"
    return f"{value[:4]}…{value[-4:]}"


def _key_info(value: str) -> dict:
    return {"configured": bool(value), "preview": _mask(value)}


@router.get("/settings")
async def get_settings() -> dict:
    """Return a redacted view of current settings (read-only)."""
    try:
        config = load_config(CONFIG_PATH)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    aliyun_ak = os.environ.get("ALIYUN_ACCESS_KEY_ID", "")
    aliyun_sk = os.environ.get("ALIYUN_ACCESS_KEY_SECRET", "")

    return {
        "vault_path": config.vault_path,
        "vault_path_default": DEFAULT_VAULT_PATH,
        "podcast_dir": config.podcast_dir,
        "asr_engine": config.asr_engine,
        "summary_provider": config.summary_provider,
        "summary_model": config.summary_model or "(provider default)",
        "summary_cooldown": config.summary_cooldown,
        "keys": {
            "dashscope": _key_info(config.dashscope_api_key),
            "poe": _key_info(config.poe_api_key),
            "openai": _key_info(config.openai_api_key),
            "tingwu_app_id": _key_info(config.tingwu_app_id),
            "aliyun_access_key_id": _key_info(aliyun_ak),
            "aliyun_access_key_secret": _key_info(aliyun_sk),
        },
    }


@router.put("/settings")
async def update_settings(payload: dict) -> dict:
    """Persist edited settings to fixed canonical paths.

    - YAML fields (``vault_path``, ``podcast_dir``, ``asr_engine``, ``summary_cooldown``)
      go to ``config.yaml`` preserving comments.
    - Other fields (API keys, summary provider) go to ``.env``.
    - **An empty string value for any key means "leave unchanged"** — protects against
      accidentally wiping a key when the user only changed something else.
    - Pass ``null`` to explicitly clear a value.

    Vault path is validated to be an existing writable directory.

    The write paths are fixed canonical constants (see ``src/web/paths.py``);
    clients **cannot** redirect writes via query parameters.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")

    yaml_updates: dict[str, object] = {}
    env_updates: dict[str, str | None] = {}

    for key, raw in payload.items():
        if raw == "":
            continue  # leave unchanged
        if key in _YAML_FIELDS:
            yaml_updates[key] = raw
        elif key in _ENV_KEY_MAP:
            env_updates[_ENV_KEY_MAP[key]] = raw if raw is not None else None

    # Validate up front so a failure can't leave a half-applied state
    if "vault_path" in yaml_updates:
        raw_vp = str(yaml_updates["vault_path"])
        vp_str = _clean_path_input(raw_vp)
        # Persist the cleaned value so future loads aren't tripped by the same quotes
        yaml_updates["vault_path"] = vp_str
        vp = Path(vp_str).expanduser()
        if not vp.exists():
            hint = "（路径不存在；如果是从命令行复制的，去掉两端的引号再保存）"
            raise HTTPException(
                status_code=400,
                detail=f"vault_path 不存在：{vp_str} {hint}",
            )
        if not vp.is_dir():
            raise HTTPException(
                status_code=400,
                detail=f"vault_path 不是目录：{vp_str}",
            )
        if not os.access(vp, os.W_OK):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"vault_path 不可写：{vp_str}（macOS 用户请到 系统设置 → 隐私与安全性 → "
                    "完全磁盘访问 把 Terminal 或 fm2note 加入白名单）"
                ),
            )

    if "podcast_dir" in yaml_updates:
        yaml_updates["podcast_dir"] = _clean_path_input(str(yaml_updates["podcast_dir"]))

    # Build both new file contents up front, then commit both within the lock.
    # Two-phase ensures we never persist YAML without ENV (or vice versa) on a
    # partial failure — the window between the two os.replace() calls is microseconds.
    yaml_text: str | None = None
    env_text: str | None = None
    if yaml_updates:
        yaml_text = _build_yaml_text(CONFIG_PATH, yaml_updates)
    if env_updates:
        env_text = build_env_text(ENV_PATH, env_updates)

    async with locks.yaml_lock, locks.env_lock:
        yaml_tmp: str | None = None
        env_tmp: str | None = None
        try:
            # Stage 1: write both temp files (no on-disk commit yet)
            if yaml_text is not None:
                Path(CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)
                yaml_tmp = stage_atomic_write(CONFIG_PATH, yaml_text)
            if env_text is not None:
                env_tmp = stage_atomic_write(ENV_PATH, env_text)

            # Stage 2: commit both back-to-back. If either replace fails, we
            # cleanup the un-committed temp and report 500.
            if yaml_tmp is not None:
                os.replace(yaml_tmp, CONFIG_PATH)
                yaml_tmp = None
            if env_tmp is not None:
                os.replace(env_tmp, ENV_PATH)
                env_tmp = None

            # Reflect new env values to current process so subsequent reads pick them up
            if env_updates:
                for env_key, val in env_updates.items():
                    if val is None:
                        os.environ.pop(env_key, None)
                    else:
                        os.environ[env_key] = val
        except Exception as e:
            # Sanitize log: error message may quote AK/SK that the user typed
            logger.warning("settings update failed: {}", type(e).__name__)
            raise HTTPException(status_code=500, detail="settings update failed") from e
        finally:
            # Cleanup any un-committed temp files
            if yaml_tmp is not None:
                Path(yaml_tmp).unlink(missing_ok=True)
            if env_tmp is not None:
                Path(env_tmp).unlink(missing_ok=True)

    return {
        "ok": True,
        "yaml_keys_updated": sorted(yaml_updates.keys()),
        "env_keys_updated": sorted(env_updates.keys()),
        "restart_required": bool(env_updates),
    }


def _build_yaml_text(config_path: str, updates: dict) -> str:
    doc = load_yaml(config_path)
    if doc is None:
        from ruamel.yaml.comments import CommentedMap

        doc = CommentedMap()
    for k, v in updates.items():
        doc[k] = v
    return dump_yaml_text(doc)
