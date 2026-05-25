"""Single source of truth for every filesystem path FM2note touches.

Before v1.5.2 there were three parallel notions of "where things live":

  * CLI commands accepted ``--config-path`` and resolved everything else
    relative to whatever the user passed.
  * Web routes hardcoded ``src.web.paths.CONFIG_PATH`` (just ``config/config.yaml``,
    CWD-relative).
  * Per-module constants like ``src/summarizer/pending.py``'s
    ``PENDING_DIR = Path("data/pending_summaries")`` resolved differently
    depending on what CWD the launcher script set.

The CWD-relative paths broke when ``fm2note app`` (PyWebView) was started
by double-clicking from Finder (CWD becomes ``/``), silently writing pending
summaries to ``/data/...`` and history queries returning empty.

This module exposes one ``AppPaths`` object, ``app_paths``, whose values
are anchored to the *project root* (or whatever the user explicitly sets
via ``configure()`` / ``FM2NOTE_HOME`` env var). Everyone — CLI, Web,
background daemon, summarizer — imports from here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock


def _detect_project_root() -> Path:
    """Find the project root by walking up from this file.

    This file lives at ``<root>/src/app_paths.py`` (pip-installed: in
    site-packages, but no ``config/`` directory there — then we fall back
    to CWD). For source checkouts we anchor to ``<root>``. For pip
    installs we anchor to the user's CWD, which is normally where they
    ran ``fm2note`` and where their ``config/`` lives.
    """
    here = Path(__file__).resolve()
    # Walk up looking for the marker (pyproject.toml beats CWD heuristics).
    for parent in [here.parent, *here.parents]:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


@dataclass
class AppPaths:
    """Resolved absolute paths. Always anchored to ``home`` so they are
    never CWD-relative at use time."""

    home: Path
    config: Path
    subscriptions: Path
    env: Path
    data_dir: Path
    db: Path
    pending_dir: Path
    temp_dir: Path
    logs_dir: Path

    @classmethod
    def from_home(cls, home: Path) -> AppPaths:
        home = home.expanduser().resolve()
        return cls(
            home=home,
            config=home / "config" / "config.yaml",
            subscriptions=home / "config" / "subscriptions.yaml",
            env=home / ".env",
            data_dir=home / "data",
            db=home / "data" / "state.db",
            pending_dir=home / "data" / "pending_summaries",
            temp_dir=home / "data" / "tmp",
            logs_dir=home / "logs",
        )


# Module-level singleton — initialized at import time from the auto-detected
# project root or the FM2NOTE_HOME env var (highest priority — lets ops
# point at a non-standard layout without code changes).
_paths_lock = Lock()
_paths: AppPaths | None = None


def _initial_paths() -> AppPaths:
    override = os.environ.get("FM2NOTE_HOME", "").strip()
    if override:
        return AppPaths.from_home(Path(override))
    return AppPaths.from_home(_detect_project_root())


def app_paths() -> AppPaths:
    """Return the active AppPaths singleton (auto-initialized)."""
    global _paths
    if _paths is None:
        with _paths_lock:
            if _paths is None:
                _paths = _initial_paths()
    return _paths


def configure(home: Path) -> AppPaths:
    """Override the singleton — used by tests and by CLI commands that
    accept ``--config-path`` to relocate the entire layout."""
    global _paths
    with _paths_lock:
        _paths = AppPaths.from_home(home)
    return _paths


def reset() -> None:
    """Test helper — clear the singleton so the next ``app_paths()`` call
    re-detects from env / project root."""
    global _paths
    with _paths_lock:
        _paths = None
