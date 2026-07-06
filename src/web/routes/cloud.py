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

v1.6.1: download now also dedups by ``frontmatter source`` field, not just
by target file path. Previously a vault file named ``Ep 25｜油价.md`` (using
unicode full-width pipe) and an incoming download named ``Ep 25 _ 油价.md``
(safe-filename sanitized ASCII pipe) had different file paths so both got
written — same episode, two .md files. The new ``_scan_existing_guids``
helper builds a {normalized-guid → path} map for the target podcast folder
and skips downloads whose source URL already exists there under any name.
"""

from __future__ import annotations

import asyncio
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
_DOWNLOAD_METADATA_LIMIT = 1000
_DOWNLOAD_FETCH_CONCURRENCY = 8


def _client() -> SharedCacheClient | None:
    return SharedCacheClient.from_env()


def _safe_filename(name: str, max_len: int = 180) -> str:
    """Sanitize a podcast/episode name into a filesystem-safe stem.

    Mirrors the rules ``ObsidianWriter`` uses when it constructs the
    original ``<date>-<title>.md`` filename. Empty input becomes
    ``"untitled"`` so the resulting path never has a bare extension.

    v1.6.2 fix (Codex S1): if a malicious cache row sets ``podcast_name`` to
    ``..`` or ``.``, ``_ILLEGAL_FILENAME_CHARS`` lets it through (it only
    strips ``/`` and friends, not bare dots), and the resulting path would
    escape ``podcast_root``. Reject pure-dot inputs explicitly. The
    caller still runs an ``is_relative_to`` check at write time as defense
    in depth.
    """
    name = _ILLEGAL_FILENAME_CHARS.sub("_", name).strip()
    if not name or name in {".", ".."} or set(name) == {"."}:
        return "untitled"
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name


# v1.6.1: server stores guids in "https:/host/..." form (single slash after
# colon) because FastAPI {guid:path} routing collapses %2F%2F → /, but
# local .md frontmatter writes the original "https://host/..." (double
# slash). Normalize the leading URI scheme so the dedup check matches
# regardless of which form we're holding.
#
# v1.6.2 fix (Codex S2): only collapse the *leading* scheme delimiter, not
# every ``://`` substring — otherwise an opaque guid like ``foo://bar://baz``
# (extremely rare but possible in non-URL guids) would get its mid-string
# ``://`` folded too, breaking comparison and silently masking a missing
# cache row as "already there". Anchor the regex at start-of-string +
# match only one ``:/+`` run.
_SCHEME_PREFIX_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):/{2,}")


def _normalize_guid(guid: str) -> str:
    """Collapse a URI's leading ``scheme://`` to ``scheme:/`` to match the
    sidecar's stored form. Non-URI guids and any further ``://`` substrings
    in the path are left untouched."""
    return _SCHEME_PREFIX_RE.sub(r"\1:/", guid, count=1)


# Match the same frontmatter parse the batch-upload scripts use — only need
# the source field, so a tiny regex over the first ~2 KB is enough (full
# YAML parse would pull in pyyaml just for this hot loop).
_FM_BLOCK_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_FM_SOURCE_RE = re.compile(r'^source:\s*"?([^"\n]*)"?', re.MULTILINE)


def _scan_existing_guids(podcast_dir: Path) -> dict[str, Path]:
    """Build {normalized-guid: filepath} for every .md in ``podcast_dir``.

    Lets the download endpoint dedup by ``frontmatter.source`` (the
    episode's RSS guid) instead of just by destination file path — so we
    don't re-download an episode whose vault counterpart happens to have a
    different filename shape (e.g. ``｜`` vs ``_`` vs space). Returns an
    empty dict if ``podcast_dir`` doesn't exist or is empty.

    Only reads the first 2 KB of each file — frontmatter is always at the
    top, so this is cheap even for 100+ episode folders.
    """
    out: dict[str, Path] = {}
    if not podcast_dir.is_dir():
        return out
    for mf in podcast_dir.glob("*.md"):
        try:
            head = mf.open("r", encoding="utf-8", errors="ignore").read(2048)
        except OSError:
            continue
        m = _FM_BLOCK_RE.match(head)
        if not m:
            continue
        src_m = _FM_SOURCE_RE.search(m.group(1))
        if not src_m:
            continue
        src = src_m.group(1).strip()
        if src:
            out[_normalize_guid(src)] = mf
    return out


async def _fetch_many(client: SharedCacheClient, guids: list[str]) -> dict[str, str | None]:
    """Fetch selected cache entries concurrently.

    Real SharedCacheClient has a connection-reusing ``fetch_many`` method.
    Tests sometimes monkeypatch a lightweight fake with only ``fetch``; keep
    that path concurrent too so the route behavior stays representative.
    """
    if isinstance(client, SharedCacheClient):
        return await client.fetch_many(guids, concurrency=_DOWNLOAD_FETCH_CONCURRENCY)
    sem = asyncio.Semaphore(_DOWNLOAD_FETCH_CONCURRENCY)

    async def _one(guid: str) -> tuple[str, str | None]:
        async with sem:
            return guid, await client.fetch(guid)

    pairs = await asyncio.gather(*(_one(guid) for guid in guids))
    return dict(pairs)


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

    # We need podcast_name + title to build a real path. The cloud page lists
    # up to 500 rows, while the sidecar hard-caps LIST at 1k; ask for that
    # cap so selecting older visible rows still has metadata.
    listing = await client.list_items(limit=_DOWNLOAD_METADATA_LIMIT)
    meta_by_guid: dict[str, dict] = {}
    for row in listing:
        guid = row.get("guid") if isinstance(row, dict) else None
        if isinstance(guid, str):
            meta_by_guid[guid] = row
            meta_by_guid[_normalize_guid(guid)] = row

    results: list[dict | None] = []
    pending: list[dict] = []
    # v1.6.1: cache per-podcast guid→path scan so we don't re-scan once per
    # downloaded file. Lazy populated.
    existing_by_podcast: dict[Path, dict[str, Path]] = {}
    for guid in raw_guids:
        slot = len(results)
        if not isinstance(guid, str) or not guid.strip():
            results.append({"guid": str(guid), "ok": False, "reason": "invalid_guid"})
            continue
        meta = meta_by_guid.get(guid) or meta_by_guid.get(_normalize_guid(guid))
        # Fall back to placeholders if the listing didn't include this guid —
        # e.g. it was uploaded by a pre-v1.6 client (no podcast_name) and the
        # listing capped before we saw it. Better to download under "未知"
        # than to silently skip the user's request.
        podcast_name = (meta or {}).get("podcast_name") or "（未知）"
        title = (meta or {}).get("title") or guid[:60]

        target_dir = podcast_root / _safe_filename(podcast_name)
        norm_guid = _normalize_guid(guid)

        # v1.6.1: guid-level dedup BEFORE fetching content (saves a network
        # round-trip + cache_sidecar load when the episode is already in vault
        # under a different filename). Only consult the scan when not
        # overwriting — overwrite=True means user explicitly wants to refresh.
        if not overwrite:
            if target_dir not in existing_by_podcast:
                existing_by_podcast[target_dir] = _scan_existing_guids(target_dir)
            existing_path = existing_by_podcast[target_dir].get(norm_guid)
            if existing_path is not None:
                results.append(
                    {
                        "guid": guid,
                        "ok": False,
                        "reason": "already_exists_by_source",
                        "path": str(existing_path),
                    }
                )
                continue

        target_path = target_dir / f"{_safe_filename(title)}.md"

        # v1.6.2 fix (Codex S1 defense in depth): even after _safe_filename,
        # confirm the resolved path lives under podcast_root before any
        # write. Catches symlink-trickery / absolute-path leakage in
        # podcast_name or title that the regex didn't anticipate.
        try:
            resolved = target_path.resolve()
            if not resolved.is_relative_to(podcast_root.resolve()):
                results.append(
                    {
                        "guid": guid,
                        "ok": False,
                        "reason": "path_escapes_vault",
                        "detail": f"refused write outside {podcast_root}",
                    }
                )
                continue
        except (OSError, ValueError) as e:
            results.append(
                {
                    "guid": guid,
                    "ok": False,
                    "reason": "path_resolve_failed",
                    "detail": f"{type(e).__name__}: {e}",
                }
            )
            continue

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

        results.append(None)
        pending.append(
            {
                "slot": slot,
                "guid": guid,
                "target_dir": target_dir,
                "target_path": target_path,
            }
        )

    fetched = await _fetch_many(client, [item["guid"] for item in pending])
    ok_count = 0
    for item in pending:
        guid = item["guid"]
        target_dir = item["target_dir"]
        target_path = item["target_path"]
        content = fetched.get(guid)
        if content is None:
            results[item["slot"]] = {"guid": guid, "ok": False, "reason": "cache_miss"}
            continue

        target_dir.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and not overwrite:
            results[item["slot"]] = {
                "guid": guid,
                "ok": False,
                "reason": "already_exists",
                "path": str(target_path),
            }
            continue
        try:
            target_path.write_text(content, encoding="utf-8")
        except OSError as e:
            logger.warning("cloud download write failed for {}: {}", guid, e)
            results[item["slot"]] = {
                "guid": guid,
                "ok": False,
                "reason": "write_failed",
                "detail": f"{type(e).__name__}: {e}",
            }
            continue
        ok_count += 1
        results[item["slot"]] = {"guid": guid, "ok": True, "path": str(target_path)}

    return {"ok": True, "downloaded": ok_count, "items": [r for r in results if r is not None]}
