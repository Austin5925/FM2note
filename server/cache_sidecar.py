"""FM2note shared transcript cache sidecar.

A minimal FastAPI service that stores rendered Markdown notes keyed by RSS
``episode.guid`` so two users sharing the same subscriptions don't both pay
DashScope / Poe for the same episode. See v1.4.16 in CLAUDE.md.

Endpoints:
  POST /cache/{guid}   {"content": "..."}   — upsert (last-write-wins)
  GET  /cache/{guid}                          — 200 with body or 404
  GET  /healthz                               — liveness

Auth: every endpoint except /healthz requires
  Authorization: Bearer <SHARED_CACHE_TOKEN>

Storage: SQLite via aiosqlite. Sized for tens of thousands of episodes —
the cache row is content text + timestamps + uploader fingerprint, no audio.

Deployment: drop this file behind any reverse proxy that terminates TLS
(your existing RSSHub nginx works). Container recipe in docker-compose.cache.yaml.
"""

from __future__ import annotations

import asyncio
import hmac
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

DB_PATH = os.environ.get("CACHE_DB_PATH", "/data/fm2note-cache.db")
SHARED_CACHE_TOKEN = os.environ.get("SHARED_CACHE_TOKEN", "").strip()
# Cap any single upload — rendered notes are typically 5-50 KB. 5 MB is a
# very generous ceiling that still rules out abuse / accidents.
MAX_CONTENT_BYTES = int(os.environ.get("CACHE_MAX_BYTES", str(5 * 1024 * 1024)))

# guid is a free-form RSS string. Restrict the in-URL representation to keep
# routing predictable; clients should hex-encode anything weirder. SQLite
# stores the raw guid in the body, not the URL.
SAFE_GUID_LEN = 256

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    guid TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    uploader_fp TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""


@asynccontextmanager
async def _lifespan(app: FastAPI):
    if not SHARED_CACHE_TOKEN:
        raise RuntimeError(
            "SHARED_CACHE_TOKEN env var is required. Generate with: "
            "python -c 'import secrets; print(secrets.token_hex(32))'"
        )
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    app.state.db = await aiosqlite.connect(DB_PATH)
    # v1.4.16 Code Review fix: aiosqlite serializes only within one coroutine;
    # two concurrent FastAPI requests sharing this connection would interleave
    # execute()/commit() pairs and possibly cross-contaminate writes. Serialize
    # writes with an explicit lock. Read-only paths (SELECT) also go through
    # this lock for simplicity — the cost is negligible for our access pattern.
    app.state.db_lock = asyncio.Lock()
    await app.state.db.execute(_SCHEMA)
    await app.state.db.commit()
    try:
        yield
    finally:
        await app.state.db.close()


app = FastAPI(title="FM2note shared cache", version="1.4.16", lifespan=_lifespan)


@app.middleware("http")
async def _enforce_body_size_limit(request, call_next):
    """Reject oversized requests BEFORE FastAPI buffers the whole body.

    v1.4.16 Codex audit fix #6: the per-route ``MAX_CONTENT_BYTES`` check
    only runs after FastAPI has already loaded the full JSON body into
    memory. An attacker could exhaust server memory by POSTing a multi-GB
    body. Check the ``Content-Length`` header up front and 413 the
    request before any buffering happens. Requests without
    ``Content-Length`` (chunked) fall through to the per-route check —
    httpx always sets it so our own client is unaffected.
    """
    cl = request.headers.get("content-length")
    if cl:
        try:
            if int(cl) > MAX_CONTENT_BYTES:
                return JSONResponse(
                    {"detail": f"body exceeds {MAX_CONTENT_BYTES} bytes"},
                    status_code=413,
                )
        except ValueError:
            return JSONResponse(
                {"detail": "invalid Content-Length"}, status_code=400
            )
    return await call_next(request)


def _require_auth(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    presented = authorization[len("Bearer ") :].strip()
    # v1.4.16 Code Review fix: use stdlib hmac.compare_digest. The previous
    # hand-rolled _ct_equal had an early-exit on len mismatch that leaked
    # token length via response timing; hmac.compare_digest handles
    # different lengths internally without short-circuiting and is
    # implemented in C with documented timing-safe guarantees.
    if not hmac.compare_digest(presented.encode("utf-8"), SHARED_CACHE_TOKEN.encode("utf-8")):
        raise HTTPException(status_code=401, detail="bad token")


def _validate_guid(guid: str) -> None:
    if not guid:
        raise HTTPException(status_code=400, detail="guid is required")
    if len(guid) > SAFE_GUID_LEN:
        raise HTTPException(status_code=400, detail=f"guid too long (>{SAFE_GUID_LEN})")


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "version": "1.4.16"}


@app.get("/cache/{guid:path}", response_model=None)
async def get_cache(guid: str, _: None = Depends(_require_auth)) -> JSONResponse:
    """JSON response; 200 with payload or 404 with {ok: False}."""
    _validate_guid(guid)
    # v1.4.16 Code Review fix #1: serialize all DB access through the lock so
    # concurrent FastAPI requests can't interleave statements on the shared
    # aiosqlite connection.
    async with app.state.db_lock:
        cursor = await app.state.db.execute(
            "SELECT content, uploader_fp, updated_at FROM notes WHERE guid=?", (guid,)
        )
        row = await cursor.fetchone()
    if row is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    content, fp, updated_at = row
    return JSONResponse(
        {
            "ok": True,
            "guid": guid,
            "content": content,
            "uploader_fp": fp,
            "updated_at": updated_at,
        }
    )


@app.post("/cache/{guid:path}")
async def post_cache(guid: str, payload: dict, _: None = Depends(_require_auth)) -> dict:
    _validate_guid(guid)
    content = (payload or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=400, detail="content (non-empty string) is required")
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise HTTPException(
            status_code=413, detail=f"content exceeds {MAX_CONTENT_BYTES} bytes"
        )
    uploader_fp = str((payload or {}).get("uploader_fp", ""))[:64]
    now = time.time()

    # Upsert with last-write-wins — both users uploading the same episode is
    # the documented happy path (Codex v1.4.16 research §6); their notes are
    # functionally identical, so neither client "loses".
    #
    # v1.5.4: serialize through db_lock — v1.4.16 Code Review fix #1 patched
    # get_cache but missed the upsert path; under concurrent uploads two
    # execute()/commit() pairs could interleave on the shared aiosqlite
    # connection and lose one writer's row entirely.
    async with app.state.db_lock:
        await app.state.db.execute(
            """INSERT INTO notes (guid, content, uploader_fp, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guid) DO UPDATE SET
                 content=excluded.content,
                 uploader_fp=excluded.uploader_fp,
                 updated_at=excluded.updated_at""",
            (guid, content, uploader_fp, now, now),
        )
        await app.state.db.commit()
    return {"ok": True, "guid": guid, "updated_at": now}


def main():
    """uvicorn entry point for running standalone (Docker default)."""
    import uvicorn

    uvicorn.run(
        "server.cache_sidecar:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8765")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
