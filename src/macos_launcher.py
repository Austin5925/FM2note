"""Finder-friendly launcher used by the packaged macOS app.

The normal CLI expects users to run FM2note from a directory containing
``config/``, ``data/`` and ``.env``. A real ``.app`` launched from Finder does
not have that working-directory contract, so this entry point anchors runtime
state under ``~/Library/Application Support/FM2note`` before delegating to the
existing ``fm2note app`` command.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from src.macos_service import (
    is_background_auto_start_disabled,
    launchd_plist_matches,
    macos_status,
)

APP_SUPPORT_HOME = Path.home() / "Library" / "Application Support" / "FM2note"
PROFILE_RESOURCE_DIR = "FM2noteProfile"
PROFILE_MARKER = ".fm2note_profile_applied"
PROFILE_FILES = (
    Path("config/config.yaml"),
    Path("config/subscriptions.yaml"),
    Path(".env"),
)


def default_home() -> Path:
    """Return the runtime home for the desktop bundle.

    ``FM2NOTE_HOME`` remains the escape hatch for development and support
    scenarios where a user wants the app to reuse an existing checkout/config.
    """
    override = os.environ.get("FM2NOTE_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return APP_SUPPORT_HOME.expanduser().resolve()


def prepare_home(home: Path | None = None, *, desktop_app: bool = True) -> Path:
    """Create and enter the desktop app runtime home."""
    resolved = (home or default_home()).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    os.environ["FM2NOTE_HOME"] = str(resolved)
    if desktop_app:
        os.environ["FM2NOTE_DESKTOP_APP"] = "1"
    else:
        os.environ.pop("FM2NOTE_DESKTOP_APP", None)
    os.chdir(resolved)
    return resolved


def bundled_profile_dir() -> Path | None:
    """Return the optional profile directory embedded in the app bundle."""
    override = os.environ.get("FM2NOTE_PROFILE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    executable = Path(sys.executable).resolve()
    parents = executable.parents
    if len(parents) >= 2:
        candidate = parents[1] / "Resources" / PROFILE_RESOURCE_DIR
        if candidate.is_dir():
            return candidate
    return None


def apply_bundled_profile(home: Path, profile_dir: Path | None = None) -> list[Path]:
    """Copy bundled first-run config files without overwriting user edits."""
    profile = profile_dir or bundled_profile_dir()
    if not profile or not profile.is_dir():
        return []

    runtime_home = home.expanduser().resolve()
    marker = runtime_home / PROFILE_MARKER
    if marker.exists():
        return []

    copied: list[Path] = []
    for rel in PROFILE_FILES:
        src = profile / rel
        if not src.is_file():
            continue
        dst = runtime_home / rel
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)

    marker.write_text(
        "FM2note bundled profile applied once. Delete this file to re-apply "
        "missing bundled files on next app launch.\n",
        encoding="utf-8",
    )
    return copied


def ensure_initialized(home: Path | None = None) -> None:
    """Create skeleton config files on first desktop launch."""
    runtime_home = (home or Path.cwd()).expanduser().resolve()
    required = (
        runtime_home / "config" / "config.yaml",
        runtime_home / "config" / "subscriptions.yaml",
        runtime_home / ".env",
    )
    if all(path.exists() for path in required):
        return

    from main import cli

    cli.main(args=["init"], prog_name="FM2note", standalone_mode=False)


def app_args() -> list[str]:
    """Build the CLI args for the desktop window command."""
    args = ["app"]
    port = os.environ.get("FM2NOTE_PORT", "").strip()
    if port:
        args.extend(["--port", port])
    return args


def cli_args_from_argv(argv: list[str]) -> list[str]:
    """Return CLI args passed to the frozen app, ignoring Finder launch noise."""
    args = [arg for arg in argv if not arg.startswith("-psn_")]
    if args[:1] == ["main.py"]:
        args = args[1:]
    elif args[:2] == ["-m", "main"]:
        args = args[2:]
    return args


def background_service_args() -> list[str]:
    """Return the launchd ProgramArguments expected for this launcher."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "serve"]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py"), "serve"]


def self_cli_command(subcommand: str) -> list[str]:
    """Return a command that routes through this launcher in CLI mode."""
    if getattr(sys, "frozen", False):
        return [sys.executable, subcommand]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py"), subcommand]


def ensure_background_service(home: Path | None = None) -> dict:
    """Start the background daemon when the packaged desktop app opens.

    Settings can explicitly disable the daemon. That choice is stored in the
    runtime home so the next app launch does not silently undo it.
    """
    runtime_home = (home or Path.cwd()).expanduser().resolve()
    if platform.system() != "Darwin":
        return {"ok": True, "skipped": "unsupported-platform"}
    if is_background_auto_start_disabled(runtime_home):
        return {"ok": True, "skipped": "disabled-by-user"}

    status = macos_status()
    expected_args = background_service_args()
    if status.get("running") and launchd_plist_matches(expected_args, runtime_home):
        return {"ok": True, "skipped": "already-running"}

    try:
        proc = subprocess.run(
            self_cli_command("install-service"),
            cwd=str(runtime_home),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": (proc.stderr or proc.stdout or "install-service failed").strip()[:500],
        }
    return {"ok": True, "output": proc.stdout.strip()}


def main() -> None:
    """Prepare desktop state and launch the existing PyWebView app."""
    cli_args = cli_args_from_argv(sys.argv[1:])
    home = prepare_home(desktop_app=not cli_args)
    apply_bundled_profile(home)
    ensure_initialized(home)
    if not cli_args:
        ensure_background_service(home)

    from main import cli

    cli.main(args=cli_args or app_args(), prog_name="FM2note", standalone_mode=True)


if __name__ == "__main__":
    main()
