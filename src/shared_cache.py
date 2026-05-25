"""Client for the FM2note shared-cache sidecar.

When configured (``SHARED_CACHE_URL`` + ``SHARED_CACHE_TOKEN`` env vars),
the pipeline uploads each finished note to the shared cache and the RSS
poller checks the cache before queuing an episode for transcription. When
NOT configured, all methods are no-ops — single-user deployments are
unaffected.

Failures are always logged and swallowed: the shared cache is an
optimization, not a dependency. A flaky cache must never break the local
pipeline or block transcription.
"""

from __future__ import annotations

import os
from hashlib import sha256
from urllib.parse import quote

import httpx
from loguru import logger

# Network timeout in seconds for cache GET/POST. Short on purpose: the cache
# is a "nice-to-have" — if it doesn't answer in 5s we'd rather just do the
# work locally than wait.
#
# Audit note (v1.4.16 Codex #5): per-episode fetches are serialized in
# Pipeline.run_once, so a 50-episode catch-up against a slow cache can
# stall up to 50 × 5s. v1.5.x will batch these (see CLAUDE.md backlog);
# the 5s ceiling means an unreachable cache adds at most ~250s to a poll
# cycle that already runs at most every 3 hours, which we judged acceptable.
_TIMEOUT_SEC = 5.0
# Per-process uploader fingerprint — opaque hash of DASHSCOPE_API_KEY +
# salt, 48 bits of entropy. Used server-side only for "who uploaded what"
# attribution between two trusted users; the api key itself is never sent.
#
# Audit note (v1.4.16 Codex #4): this is computed ONCE at module import.
# If the user rotates DASHSCOPE_API_KEY without restarting fm2note, the
# fingerprint stays old. Acceptable — fingerprint is not security-critical,
# and `fm2note serve` is restarted on key rotation anyway.
_UPLOADER_FP = sha256(
    (os.environ.get("DASHSCOPE_API_KEY", "anon") + ":fm2note").encode("utf-8")
).hexdigest()[:12]


class SharedCacheClient:
    """Thin async client. Construct via :func:`from_env` to honor the
    "unconfigured = silent no-op" contract."""

    def __init__(self, base_url: str, token: str):
        self._base = base_url.rstrip("/")
        self._token = token

    @classmethod
    def from_env(cls) -> SharedCacheClient | None:
        """Return a configured client, or ``None`` if the env vars are absent.

        Callers should pattern: ``client = SharedCacheClient.from_env()`` and
        guard every call with ``if client:`` — methods on a real client
        already swallow errors, but skipping the network round-trip entirely
        is faster than mocking a no-op.
        """
        url = os.environ.get("SHARED_CACHE_URL", "").strip()
        token = os.environ.get("SHARED_CACHE_TOKEN", "").strip()
        if not url or not token:
            return None
        return cls(url, token)

    async def fetch(self, guid: str) -> str | None:
        """Return the cached Markdown for ``guid``, or ``None`` if absent.

        Returns ``None`` on miss, on auth failure, on network error, on
        timeout, on any 4xx/5xx — the local pipeline should always proceed
        as if the cache didn't exist when we can't get a confident hit.
        """
        url = self._url_for(guid)
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
                resp = await client.get(url, headers=self._auth_headers())
        except httpx.HTTPError as e:
            logger.debug("shared cache fetch network error for {}: {}", guid, type(e).__name__)
            return None

        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            logger.warning(
                "shared cache fetch HTTP {} for guid {} (len={}): treating as miss",
                resp.status_code,
                guid,
                len(guid),
            )
            return None

        try:
            body = resp.json()
        except ValueError:
            logger.warning("shared cache returned non-JSON for {}", guid)
            return None
        content = body.get("content") if isinstance(body, dict) else None
        if not isinstance(content, str) or not content.strip():
            return None
        return content

    async def upload(
        self,
        guid: str,
        content: str,
        *,
        podcast_name: str = "",
        title: str = "",
    ) -> bool:
        """Upload ``content`` (rendered Markdown) for ``guid``. Returns True
        on a successful 2xx, False otherwise. Never raises.

        v1.6: ``podcast_name`` + ``title`` are optional but strongly
        recommended — they populate the server's cloud-browse list so the
        other user's UI can render the episode by name (instead of by raw
        guid). Older server versions silently ignore unknown fields, so
        passing them is safe even before the server is upgraded.
        """
        if not content or not content.strip():
            return False
        url = self._url_for(guid)
        payload: dict = {"content": content, "uploader_fp": _UPLOADER_FP}
        if podcast_name:
            payload["podcast_name"] = podcast_name
        if title:
            payload["title"] = title
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
                resp = await client.post(
                    url,
                    headers=self._auth_headers(),
                    json=payload,
                )
        except httpx.HTTPError as e:
            logger.warning("shared cache upload network error for {}: {}", guid, type(e).__name__)
            return False
        if 200 <= resp.status_code < 300:
            return True
        logger.warning(
            "shared cache upload HTTP {} for guid {}: {}",
            resp.status_code,
            guid,
            resp.text[:200],
        )
        return False

    async def list_items(self, prefix: str = "", limit: int = 200) -> list[dict]:
        """v1.6: list episodes currently in the cache.

        Returns ``[{guid, podcast_name, title, size, updated_at}, ...]`` or
        an empty list on any error. ``prefix`` filters by
        ``podcast_name`` LIKE prefix%. ``limit`` is server-clamped.

        Like ``fetch`` and ``upload``, this swallows all transport errors —
        the cloud-browse UI should treat an empty list as "nothing to show"
        and inform the user via a UI banner that the cache may be down.
        Naming note: ``list`` would shadow the builtin; ``list_items`` is
        the explicit verb.
        """
        url = f"{self._base}/cache/list"
        params = {"limit": int(limit)}
        if prefix:
            params["prefix"] = prefix
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
                resp = await client.get(url, headers=self._auth_headers(), params=params)
        except httpx.HTTPError as e:
            logger.debug("shared cache list network error: {}", type(e).__name__)
            return []
        if resp.status_code != 200:
            logger.warning(
                "shared cache list HTTP {}: {}",
                resp.status_code,
                resp.text[:200],
            )
            return []
        try:
            body = resp.json()
        except ValueError:
            logger.warning("shared cache list returned non-JSON")
            return []
        items = body.get("items") if isinstance(body, dict) else None
        if not isinstance(items, list):
            return []
        return items

    # ---- helpers ----

    def _url_for(self, guid: str) -> str:
        # GUIDs can contain ``/`` (RSS link form) and other URL-unsafe
        # characters. quote() with safe="" handles them all; the server's
        # FastAPI route uses {guid:path} so the encoded value decodes correctly.
        return f"{self._base}/cache/{quote(guid, safe='')}"

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "fm2note-shared-cache-client/1",
        }
