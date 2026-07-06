"""Shared macOS launchd service helpers."""

from __future__ import annotations

import contextlib
import plistlib
import subprocess
from pathlib import Path

SERVICE_LABEL = "com.fm2note.serve"
BACKGROUND_DISABLED_MARKER = ".fm2note_background_disabled"


def launchd_plist_path() -> Path:
    """Return the per-user launchd plist path."""
    return Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"


def background_disabled_marker(home: Path | None = None) -> Path:
    """Return the runtime-home marker for explicit background-disable choice."""
    runtime_home = (home or Path.cwd()).expanduser().resolve()
    return runtime_home / BACKGROUND_DISABLED_MARKER


def is_background_auto_start_disabled(home: Path | None = None) -> bool:
    """True when the user explicitly disabled the background daemon."""
    return background_disabled_marker(home).exists()


def set_background_auto_start_disabled(disabled: bool, home: Path | None = None) -> None:
    """Persist or clear the explicit background-daemon disabled preference."""
    marker = background_disabled_marker(home)
    if disabled:
        marker.write_text(
            "FM2note background auto-check was disabled from the app settings.\n"
            "Delete this file or re-enable the background service in Settings to "
            "auto-start it again.\n",
            encoding="utf-8",
        )
    else:
        with contextlib.suppress(FileNotFoundError):
            marker.unlink()


def read_launchd_plist() -> dict | None:
    """Parse the launchd plist if it exists and is readable."""
    plist = launchd_plist_path()
    if not plist.exists():
        return None
    try:
        with plist.open("rb") as f:
            data = plistlib.load(f)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    return data if isinstance(data, dict) else None


def launchd_plist_matches(expected_args: list[str], expected_workdir: Path) -> bool:
    """Return whether the installed plist points at this runtime."""
    data = read_launchd_plist()
    if not data:
        return False
    if data.get("ProgramArguments") != expected_args:
        return False
    try:
        actual_workdir = Path(str(data.get("WorkingDirectory", ""))).expanduser().resolve()
    except OSError:
        return False
    return actual_workdir == expected_workdir.expanduser().resolve()


def macos_status() -> dict:
    """Read launchd state for FM2note without modifying anything."""
    plist = launchd_plist_path()
    installed = plist.exists()
    running = False
    pid: int | None = None
    if installed:
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
        "auto_start_disabled": is_background_auto_start_disabled(),
    }
