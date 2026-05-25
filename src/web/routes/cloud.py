"""Cloud-browse routes — talk to the shared cache sidecar from the local
Web UI, surface a folder/file tree, and let the user pull a selection down
into their Obsidian vault.

v1.6: server-side adds ``GET /cache/list`` + ``podcast_name`` / ``title``
columns on the ``notes`` table; this router consumes that for two endpoints:

  * ``GET  /api/cloud/list``      — list cached episodes (optionally
    filtered by ``prefix=podcast_name``). UI uses no-prefix to render the
    folder view, then per-folder to populate the episode view.
  * ``POST /api/cloud/download``  — fetch a batch of guids and write each
    to ``<vault>/<podcast_dir>/<podcast_name>/<safe-title>.md``.
    Respects an ``overwrite`` flag — default is "skip if file exists" so an
    accidental click doesn't clobber a user-edited copy.

Both endpoints require the shared cache to be configured (SHARED_CACHE_URL
+ SHARED_CACHE_TOKEN) — otherwise return ``{"ok": False, "reason":
"cache_unconfigured"}`` so the UI can show a clear empty-state banner.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from loguru import logger

from src.config import load_config
from src.shared_cache import SharedCacheClient
from src.web.paths import CONFIG_PATH

router = APIRouter(prefix="/api/cloud")

# Same illegal-filename set ObsidianWriter uses; keep in sync.
_ILLEGAL_FILENAME_CHARS = re.compile(r'[/\\:*?"<>|]')

# Hard cap on a single download batch. The server itself caps the LIST
# response, so this is just defense against a runaway click on a
# "select all" multi-folder action.
_DOWNLOAD_MAX_BATCH = 100


def _client() -> SharedCacheClient | None:
    return SharedCacheClient.from_env()


def _safe_filename(name: str, max_len: int = 180) -> str:
    """Sanitize a podcast/episode name into a filesystem-safe stem.

    Mirrors the rules ``ObsidianWriter`` uses when it constructs the
    original ``<date>-<title>.md`` filename. Empty input becomes
    ``"untitled"`` so the resulting path never has a bare extension.
    """
    name = _ILLEGAL_FILENAME_CHARS.sub("_", name).strip()
    if not name:
        return "untitled"
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name


@router.get("/list")
async def cloud_list(prefix: str = "", limit: int = 500) -> dict:
    """List cached episodes; UI groups by ``podcast_name`` to render
    folder + file views from a single response."""
    client = _client()
    if client is None:
        return {
            "ok": False,
            "reason": "cache_unconfigured",
            "detail": (
                "未配置共享缓存。请在 .env 设置 SHARED_CACHE_URL + "
                "SHARED_CACHE_TOKEN 后重启 fm2note。"
            ),
            "items": [],
        }
    items = await client.list_items(prefix=prefix, limit=limit)
    return {"ok": True, "items": items, "count": len(items)}


@router.post("/download")
async def cloud_download(payload: dict) -> dict:
    """Download a batch of cached episodes into the local vault.

    Body shape::

        {
          "guids":    ["guid-a", "guid-b", ...],   # required, max 100
          "overwrite": false                        # optional, default false
        }

    Per-item response (in ``items``):
        ``{guid, ok, reason?, path?}``
    """
    client = _client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "未配置共享缓存（SHARED_CACHE_URL/SHARED_CACHE_TOKEN）。"
                "请在 .env 设置后重启 fm2note。"
            ),
        )

    raw_guids = (payload or {}).get("guids", [])
    if not isinstance(raw_guids, list) or not raw_guids:
        raise HTTPException(status_code=400, detail="guids (non-empty list) is required")
    if len(raw_guids) > _DOWNLOAD_MAX_BATCH:
        raise HTTPException(
            status_code=400,
            detail=f"一次最多下载 {_DOWNLOAD_MAX_BATCH} 集，请分批",
        )
    overwrite = bool((payload or {}).get("overwrite", False))

    config = load_config(CONFIG_PATH)
    vault_root = Path(config.vault_path).expanduser().resolve()
    # vault_path validation already happens at config-load time / settings-page;
    # double-check the directory exists so we fail fast with a friendly error
    # rather than a per-item write exception.
    if not vault_root.is_dir():
        raise HTTPException(
            status_code=500,
            detail=f"Obsidian vault 路径不存在或不是目录：{vault_root}",
        )
    podcast_root = vault_root / config.podcast_dir

    # We need podcast_name + title to build a real path; ask the server for
    # everything matching our requested guid set in one LIST call (no per-guid
    # round trip — the server caps LIST at 1k which is well above our 100 cap).
    listing = await client.list_items(limit=_DOWNLOAD_MAX_BATCH * 2)
    meta_by_guid = {row["guid"]: row for row in listing}

    results: list[dict] = []
    ok_count = 0
    for guid in raw_guids:
        if not isinstance(guid, str) or not guid.strip():
            results.append({"guid": str(guid), "ok": False, "reason": "invalid_guid"})
            continue
        meta = meta_by_guid.get(guid)
        # Fall back to placeholders if the listing didn't include this guid —
        # e.g. it was uploaded by a pre-v1.6 client (no podcast_name) and the
        # listing capped before we saw it. Better to download under "未知"
        # than to silently skip the user's request.
        podcast_name = (meta or {}).get("podcast_name") or "（未知）"
        title = (meta or {}).get("title") or guid[:60]

        content = await client.fetch(guid)
        if content is None:
            results.append({"guid": guid, "ok": False, "reason": "cache_miss"})
            continue

        target_dir = podcast_root / _safe_filename(podcast_name)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{_safe_filename(title)}.md"

        if target_path.exists() and not overwrite:
            results.append(
                {
                    "guid": guid,
                    "ok": False,
                    "reason": "already_exists",
                    "path": str(target_path),
                }
            )
            continue
        try:
            target_path.write_text(content, encoding="utf-8")
        except OSError as e:
            logger.warning("cloud download write failed for {}: {}", guid, e)
            results.append(
                {
                    "guid": guid,
                    "ok": False,
                    "reason": "write_failed",
                    "detail": f"{type(e).__name__}: {e}",
                }
            )
            continue
        ok_count += 1
        results.append({"guid": guid, "ok": True, "path": str(target_path)})

    return {"ok": True, "downloaded": ok_count, "items": results}
