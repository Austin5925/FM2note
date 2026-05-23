from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.version import VERSION
from src.web.routes import balance, history, pages, settings_api, subscriptions, transcribe

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="FM2note Web UI", version=VERSION)

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    app.include_router(pages.router)
    app.include_router(transcribe.router)
    app.include_router(settings_api.router)
    app.include_router(history.router)
    app.include_router(subscriptions.router)
    app.include_router(balance.router)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True, "version": VERSION}

    return app


app = create_app()
