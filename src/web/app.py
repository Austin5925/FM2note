from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from src.version import VERSION
from src.web.routes import (
    balance,
    cloud,
    health,
    history,
    logs,
    pages,
    service,
    settings_api,
    subscriptions,
    transcribe,
)
from src.web.services.log_buffer import ensure_buffer_installed
from src.web.services.state_singleton import close_state_manager

_STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """v1.5.2 Code Review fix #1: actually wire up the singleton teardown
    promised by ``close_state_manager()``'s docstring. Lets SQLite checkpoint
    its WAL cleanly on shutdown and prevents the lazy-created StateManager
    from leaking past process exit.

    v1.5.3: also install the loguru-to-ring-buffer sink so the GUI log
    panel has data the moment the first request hits."""
    ensure_buffer_installed()
    yield
    await close_state_manager()


def create_app() -> FastAPI:
    app = FastAPI(title="FM2note Web UI", version=VERSION, lifespan=_lifespan)

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
    app.include_router(logs.router)
    app.include_router(cloud.router)

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
