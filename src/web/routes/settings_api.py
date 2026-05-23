from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.config import load_config

router = APIRouter(prefix="/api")


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "****"
    return f"{value[:4]}…{value[-4:]}"


@router.get("/settings")
async def get_settings(config_path: str = "config/config.yaml") -> dict:
    """Return a redacted view of current settings.

    v1.4.0: read-only. API keys are returned as masked strings.
    """
    try:
        config = load_config(config_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {
        "vault_path": config.vault_path,
        "podcast_dir": config.podcast_dir,
        "asr_engine": config.asr_engine,
        "summary_provider": config.summary_provider,
        "summary_model": config.summary_model or "(provider default)",
        "summary_cooldown": config.summary_cooldown,
        "keys": {
            "dashscope": {
                "configured": bool(config.dashscope_api_key),
                "preview": _mask(config.dashscope_api_key),
            },
            "poe": {
                "configured": bool(config.poe_api_key),
                "preview": _mask(config.poe_api_key),
            },
            "openai": {
                "configured": bool(config.openai_api_key),
                "preview": _mask(config.openai_api_key),
            },
            "tingwu_app_id": {
                "configured": bool(config.tingwu_app_id),
                "preview": _mask(config.tingwu_app_id),
            },
        },
    }
