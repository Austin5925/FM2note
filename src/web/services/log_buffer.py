"""Process-wide loguru sink + ring buffer for the GUI log panel.

v1.5.3 fix for the long-standing debt: when something breaks under
``fm2note app`` (PyWebView desktop shell), the user has no way to see
loguru output — there's no terminal attached, stderr goes nowhere. This
buffer collects every log record loguru ever emits inside this process
(capped at ``_MAX_LINES`` so memory stays bounded) and the
``/api/logs`` endpoint streams them to the settings page panel.

Callers don't touch this module directly — the loguru sink is registered
at FastAPI app startup via ``ensure_buffer_installed()``.
"""

from __future__ import annotations

import contextlib
from collections import deque
from threading import Lock
from typing import Any

from loguru import logger

# Cap memory at ~2 MB worst case (10k × 200 bytes avg).
_MAX_LINES = 10_000

_buffer: deque[dict[str, Any]] = deque(maxlen=_MAX_LINES)
_lock = Lock()
_sink_id: int | None = None
_seq = 0


def _build_record(message, seq: int) -> dict[str, Any]:
    """Project a loguru Record to a JSON-friendly dict."""
    record = message.record
    return {
        "seq": seq,
        # ISO 8601 with timezone — frontend formats locally.
        "time": record["time"].isoformat(),
        "level": record["level"].name,
        "module": record["name"],
        "line": record["line"],
        "message": record["message"],
    }


def _sink(message) -> None:
    """loguru sink callable — appended to ``_buffer`` so /api/logs can serve them.
    Sink failures must not break logging; drop on the floor.

    v1.5.3 Code Review I1 fix: hold ``_lock`` across BOTH the seq increment
    AND the deque.append so two concurrent writers can't end up appending
    out-of-seq (which would silently break the after_seq filter).
    """
    global _seq
    with contextlib.suppress(Exception), _lock:
        _seq += 1
        _buffer.append(_build_record(message, _seq))


def ensure_buffer_installed() -> None:
    """Idempotently register the buffer sink with loguru. Called once at
    FastAPI startup; subsequent calls are no-ops."""
    global _sink_id
    if _sink_id is not None:
        return
    _sink_id = logger.add(
        _sink,
        level="INFO",
        # Format string is irrelevant — _sink reads structured record fields.
        format="{message}",
        # enqueue=False so log records are visible synchronously after the
        # logger.x() call. deque.append is atomic under CPython's GIL, so
        # we don't need the worker thread enqueue provides.
        enqueue=False,
        backtrace=False,
        diagnose=False,
    )


def uninstall_buffer() -> None:
    """Test helper — remove the sink + clear the buffer.

    v1.5.3 Code Review C1 fix: also reset ``_seq`` so subsequent tests
    that filter by ``after_seq`` don't see ghost values from previous
    runs (they would silently pass-or-fail depending on test order).
    """
    global _sink_id, _seq
    if _sink_id is not None:
        with contextlib.suppress(ValueError):
            logger.remove(_sink_id)
        _sink_id = None
    _buffer.clear()
    with _lock:
        _seq = 0


def get_logs(*, after_seq: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    """Return up to ``limit`` log records with ``seq > after_seq``.

    Frontend polls with the last-seen seq to do incremental fetching.
    """
    snapshot = list(_buffer)
    if after_seq > 0:
        snapshot = [r for r in snapshot if r["seq"] > after_seq]
    return snapshot[-limit:]
