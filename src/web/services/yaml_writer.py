from __future__ import annotations

import os
from io import StringIO
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from src.web.services.env_writer import stage_atomic_write


def _make_yaml() -> YAML:
    y = YAML(typ="rt")  # round-trip mode preserves comments + order
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def load_yaml(path: str | Path) -> Any:
    path = Path(path)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return _make_yaml().load(f)


def dump_yaml_text(data: Any) -> str:
    buf = StringIO()
    _make_yaml().dump(data, buf)
    return buf.getvalue()


def dump_yaml(path: str | Path, data: Any) -> None:
    """Atomically write ``data`` back to ``path`` preserving comments / order."""
    path = Path(path)
    content = dump_yaml_text(data)
    tmp = stage_atomic_write(path, content)
    try:
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
