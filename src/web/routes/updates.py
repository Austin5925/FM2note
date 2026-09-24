from __future__ import annotations

import re

import httpx
from fastapi import APIRouter
from loguru import logger

from src.version import VERSION

router = APIRouter(prefix="/api")

_RELEASES_URL = "https://api.github.com/repos/Austin5925/FM2note/releases/latest"
_DOWNLOAD_HOST = "github.com"
_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _SEMVER.fullmatch(value.strip())
    return tuple(int(part) for part in match.groups()) if match else (0, 0, 0)


def _safe_download_url(url: str) -> str:
    parsed = httpx.URL(url)
    if parsed.scheme != "https" or parsed.host != _DOWNLOAD_HOST:
        return ""
    return str(parsed)


@router.get("/updates")
async def latest_update() -> dict:
    """Read the latest public GitHub Release without downloading or installing it."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            response = await client.get(
                _RELEASES_URL,
                headers={"Accept": "application/vnd.github+json"},
            )
        response.raise_for_status()
        release = response.json()
        tag = str(release.get("tag_name", ""))
        version = tag.lstrip("v")
        if not _SEMVER.fullmatch(version):
            raise ValueError("GitHub release has an invalid version")
        assets = [
            {
                "name": str(asset.get("name", "")),
                "download_url": _safe_download_url(str(asset.get("browser_download_url", ""))),
            }
            for asset in (release.get("assets") or [])
            if _safe_download_url(str(asset.get("browser_download_url", "")))
        ]
        return {
            "ok": True,
            "current_version": VERSION,
            "latest_version": version,
            "update_available": _version_tuple(version) > _version_tuple(VERSION),
            "release_url": _safe_download_url(str(release.get("html_url", ""))),
            "assets": assets,
        }
    except Exception as exc:
        logger.warning("update check failed: {}", type(exc).__name__)
        return {
            "ok": False,
            "current_version": VERSION,
            "latest_version": None,
            "update_available": False,
            "detail": "暂时无法连接 GitHub Releases，请稍后重试",
        }
