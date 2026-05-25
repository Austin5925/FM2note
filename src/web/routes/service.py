from __future__ import annotations

import asyncio
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from loguru import logger

router = APIRouter(prefix="/api")

SERVICE_LABEL = "com.fm2note.serve"


def _macos_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"


def _macos_status() -> dict:
    """Read launchd state for our label without modifying anything."""
    plist = _macos_plist_path()
    installed = plist.exists()
    running = False
    pid: int | None = None
    if installed:
        # `launchctl list <label>` prints a plist-ish text. PID > 0 means running.
        try:
            result = subprocess.run(
                ["launchctl", "list", SERVICE_LABEL],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line.startswith('"PID"'):
                        # Format: "PID" = 12345;
                        try:
                            num = line.split("=", 1)[1].strip().rstrip(";").strip()
                            pid = int(num)
                            running = pid > 0
                        except (ValueError, IndexError):
                            pass
                        break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return {
        "platform": "darwin",
        "installed": installed,
        "running": running,
        "pid": pid,
        "plist_path": str(plist) if installed else None,
    }


@router.get("/service/status")
async def service_status() -> dict:
    """Report whether the `fm2note serve` background service is installed/running.

    v1.5.1: the underlying ``launchctl list`` is a blocking subprocess (5s
    timeout — Codex v1.5.x audit flagged this as event-loop blocking). Wrap
    in ``asyncio.to_thread`` so other API endpoints stay responsive while
    this runs.
    """
    system = platform.system()
    if system == "Darwin":
        return await asyncio.to_thread(_macos_status)
    return {
        "platform": system.lower() or "unknown",
        "installed": False,
        "running": False,
        "pid": None,
        "plist_path": None,
    }


@router.post("/service/install")
async def service_install() -> dict:
    """Install the launchd plist so ``fm2note serve`` starts on login.

    v1.5.1: GUI users no longer need to open a terminal and run
    ``fm2note install-service`` — the settings page calls this endpoint
    behind a toggle. Subprocess runs in a worker thread to avoid blocking
    the event loop.
    """
    if platform.system() != "Darwin":
        raise HTTPException(
            status_code=400,
            detail="GUI install-service 仅支持 macOS；Linux 用户请用 systemd",
        )
    try:
        result = await asyncio.to_thread(_run_install_service)
    except Exception as e:
        logger.warning("install-service failed: {}: {}", type(e).__name__, e)
        raise HTTPException(status_code=500, detail=f"安装失败：{type(e).__name__}") from e
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "未知错误"))
    return result


@router.post("/service/uninstall")
async def service_uninstall() -> dict:
    """Remove the launchd plist (mirror of /install for the off toggle)."""
    if platform.system() != "Darwin":
        raise HTTPException(status_code=400, detail="仅支持 macOS")
    try:
        result = await asyncio.to_thread(_run_uninstall_service)
    except Exception as e:
        logger.warning("uninstall-service failed: {}: {}", type(e).__name__, e)
        raise HTTPException(status_code=500, detail=f"卸载失败：{type(e).__name__}") from e
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "未知错误"))
    return result


def _fm2note_cli_cmd(subcommand: str) -> list[str]:
    """Build a command line that invokes ``fm2note <subcommand>``.

    v1.5.1 Code Review fix: prefer the installed ``fm2note`` console script
    (works in pip-installed environments regardless of CWD). Fall back to
    ``python main.py <sub>`` when running from a source checkout where the
    script isn't on PATH. The original ``python -m main`` was fragile —
    ``main`` would resolve only when CWD contained ``main.py``.
    """
    bin_path = shutil.which("fm2note")
    if bin_path:
        return [bin_path, subcommand]
    # Source-checkout fallback: locate main.py relative to this file.
    main_py = Path(__file__).resolve().parents[3] / "main.py"
    if main_py.is_file():
        return [sys.executable, str(main_py), subcommand]
    # Last resort: try -m, may fail if main isn't on sys.path.
    return [sys.executable, "-m", "main", subcommand]


def _run_install_service() -> dict:
    """Shell-out to ``fm2note install-service`` (the CLI command). Reuses the
    existing logic without duplicating it. Returns ``{ok, output}`` or
    ``{ok: False, error}``."""
    proc = subprocess.run(
        _fm2note_cli_cmd("install-service"),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode == 0:
        return {"ok": True, "output": proc.stdout.strip()}
    return {
        "ok": False,
        "error": (proc.stderr or proc.stdout or "install failed").strip()[:500],
    }


def _run_uninstall_service() -> dict:
    proc = subprocess.run(
        _fm2note_cli_cmd("uninstall-service"),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode == 0:
        return {"ok": True, "output": proc.stdout.strip()}
    return {
        "ok": False,
        "error": (proc.stderr or proc.stdout or "uninstall failed").strip()[:500],
    }
