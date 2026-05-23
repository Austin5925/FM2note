from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.web.services.balance import fetch_balance

router = APIRouter(prefix="/api")


@router.get("/balance")
async def get_balance(refresh: bool = False):
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
