from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from src.version import VERSION
from src.web.routes import (
    balance,
    health,
    history,
    pages,
    service,
    settings_api,
    subscriptions,
    transcribe,
)

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
    app.include_router(health.router)
    app.include_router(service.router)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # FastAPI/Starlette has already routed; this is the last-resort net for
        # truly unexpected errors. HTTPException is handled separately below.
        logger.warning(
            "unhandled exception on {} {}: {}",
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": f"internal error ({type(exc).__name__})"},
        )

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True, "version": VERSION}

    return app


app = create_app()
