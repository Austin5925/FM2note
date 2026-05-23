"""Centralized canonical paths used by the web layer.

API endpoints must never accept these as HTTP-level query parameters —
that would let a client write secrets to arbitrary disk locations.
"""

from __future__ import annotations

from pathlib import Path

CONFIG_PATH: str = "config/config.yaml"
SUBSCRIPTIONS_PATH: str = "config/subscriptions.yaml"
ENV_PATH: str = ".env"


def resolve_relative(path: str) -> Path:
    """Resolve ``path`` relative to current CWD, returning an absolute Path."""
    return Path(path).resolve()
