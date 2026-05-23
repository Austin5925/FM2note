from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from fastapi import APIRouter

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
    """Report whether the `fm2note serve` background service is installed/running."""
    system = platform.system()
    if system == "Darwin":
        return _macos_status()
    # Linux / Windows — return a "not detected" structure without erroring
    return {
        "platform": system.lower() or "unknown",
        "installed": False,
        "running": False,
        "pid": None,
        "plist_path": None,
    }
