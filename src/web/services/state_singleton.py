"""Process-wide StateManager singleton for the Web layer.

v1.5.2 Code Review #6 + Codex debt fix: before this, every Web route that
needed state.db opened its own ``aiosqlite`` connection per request:

  * ``/api/history`` — open, query all, close (Code Review A3).
  * ``/api/subscriptions/preview`` — open, run ``is_processed`` per
    episode, close.
  * ``POST /api/subscriptions`` ``_apply_backfill_strategy`` — open, mark
    backfill batch, close.

Each open+close pair has measurable overhead, and concurrent connections
on the same SQLite file rely on SQLite's default file-lock contention
(see Codex finding about ``mark_status`` SELECT-then-INSERT race). The
singleton here is opened once at FastAPI startup, shared by all routes,
and reuses the same ``aiosqlite`` connection — making mark_status
transactions actually serializable.

Routes that need it call ``await get_state_manager(db_path)`` instead of
constructing their own.
"""

from __future__ import annotations

import asyncio
import contextlib

from src.monitor.state import StateManager

_lock = asyncio.Lock()
_state: StateManager | None = None
_state_db_path: str | None = None


async def get_state_manager(db_path: str) -> StateManager:
    """Return the process-wide StateManager, creating it on first call.

    If a different ``db_path`` is requested (e.g. tests changing
    fixtures), the previous one is closed and a fresh manager opened —
    the singleton is per-(db_path), keyed on the path string.
    """
    global _state, _state_db_path
    async with _lock:
        if _state is None or _state_db_path != db_path:
            if _state is not None:
                with contextlib.suppress(Exception):
                    await _state.close()
            _state = StateManager(db_path)
            await _state.init()
            _state_db_path = db_path
        return _state


async def close_state_manager() -> None:
    """Close the singleton — called by the FastAPI lifespan on shutdown,
    and by tests that want to reset state."""
    global _state, _state_db_path
    async with _lock:
        if _state is not None:
            with contextlib.suppress(Exception):
                await _state.close()
            _state = None
            _state_db_path = None


def reset_for_tests() -> None:
    """Synchronous test helper — drop the singleton reference without
    awaiting close(). Safe because each test gets its own fresh tmp_path
    fixture; the abandoned connection will be GC'd."""
    global _state, _state_db_path
    _state = None
    _state_db_path = None
