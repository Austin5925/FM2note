from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.config import load_config
from src.web.paths import CONFIG_PATH
from src.web.services.balance import fetch_balance

router = APIRouter(prefix="/api")


@router.get("/balance")
async def get_balance(refresh: bool = False):
    try:
        config = load_config(CONFIG_PATH)
    except Exception:
        config = None

    if config is not None and config.asr_engine == "poe":
        if not config.poe_api_key:
            return JSONResponse({"configured": False, "provider": "poe"})
        return JSONResponse(
            {
                "configured": True,
                "mode": "unlimited",
                "provider": "poe",
                "label": "无限",
                "model": config.poe_asr_model,
            }
        )

    state = await fetch_balance(force_refresh=refresh)
    if not state.configured:
        return JSONResponse({"configured": False})
    if state.snapshot is None:
        return JSONResponse({"configured": True, "error": state.error})
    s = state.snapshot
    return JSONResponse(
        {
            "configured": True,
            "available_amount": s.available_amount,
            "available_cash_amount": s.available_cash_amount,
            "currency": s.currency,
            "alert_level": s.alert_level,
        }
    )
