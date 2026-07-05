"""Finder-friendly launcher used by the packaged macOS app.

The normal CLI expects users to run FM2note from a directory containing
``config/``, ``data/`` and ``.env``. A real ``.app`` launched from Finder does
not have that working-directory contract, so this entry point anchors runtime
state under ``~/Library/Application Support/FM2note`` before delegating to the
existing ``fm2note app`` command.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_SUPPORT_HOME = Path.home() / "Library" / "Application Support" / "FM2note"


def default_home() -> Path:
    """Return the runtime home for the desktop bundle.

    ``FM2NOTE_HOME`` remains the escape hatch for development and support
    scenarios where a user wants the app to reuse an existing checkout/config.
    """
    override = os.environ.get("FM2NOTE_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return APP_SUPPORT_HOME.expanduser().resolve()


def prepare_home(home: Path | None = None) -> Path:
    """Create and enter the desktop app runtime home."""
    resolved = (home or default_home()).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    os.environ["FM2NOTE_HOME"] = str(resolved)
    os.chdir(resolved)
    return resolved


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


def main() -> None:
    """Prepare desktop state and launch the existing PyWebView app."""
    home = prepare_home()
    ensure_initialized(home)

    from main import cli

    cli.main(args=app_args(), prog_name="FM2note", standalone_mode=True)


if __name__ == "__main__":
    main()
