from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.version import VERSION

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter()


def _ctx(active: str) -> dict:
    return {"version": VERSION, "active": active}


@router.get("/", response_class=HTMLResponse)
async def page_transcribe(request: Request):
    return templates.TemplateResponse(request, "transcribe.html", _ctx("transcribe"))


@router.get("/history", response_class=HTMLResponse)
async def page_history(request: Request):
    return templates.TemplateResponse(request, "history.html", _ctx("history"))


@router.get("/subscriptions", response_class=HTMLResponse)
async def page_subscriptions(request: Request):
    return templates.TemplateResponse(request, "subscriptions.html", _ctx("subscriptions"))


@router.get("/settings", response_class=HTMLResponse)
async def page_settings(request: Request):
    return templates.TemplateResponse(request, "settings.html", _ctx("settings"))


@router.get("/cloud", response_class=HTMLResponse)
async def page_cloud(request: Request):
    return templates.TemplateResponse(request, "cloud.html", _ctx("cloud"))
