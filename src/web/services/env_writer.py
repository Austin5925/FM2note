from __future__ import annotations

import os
import re
import shlex
import tempfile
from pathlib import Path

_EXPORT_LINE = re.compile(r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<rest>.*)$")


def _quote(value: str) -> str:
    """Quote a value so it survives a roundtrip in a POSIX shell-style .env file."""
    if value == "":
        return '""'
    if re.fullmatch(r"[A-Za-z0-9_./:@\-+%]+", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _parse_value(rest: str) -> str:
    rest = rest.rstrip()
    if not (rest.startswith('"') or rest.startswith("'")):
        hash_idx = rest.find("#")
        if hash_idx >= 0:
            rest = rest[:hash_idx].rstrip()
    try:
        parts = shlex.split(rest, posix=True)
    except ValueError:
        return rest
    return parts[0] if parts else ""


def read_env(path: str | Path) -> dict[str, str]:
    """Parse a .env file into a dict. Honors ``export VAR=...`` prefix."""
    path = Path(path)
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _EXPORT_LINE.match(line)
        if not m:
            continue
        result[m.group("key")] = _parse_value(m.group("rest"))
    return result


def build_env_text(path: str | Path, updates: dict[str, str | None]) -> str:
    """Compute the new file content after applying ``updates``, without writing.

    Rules: existing keys updated in place (preserving ``export`` prefix /
    surrounding whitespace); comments + blank lines passthrough; new keys
    appended; ``None`` deletes a key; empty string is written as ``""``.
    """
    path = Path(path)
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = original.splitlines(keepends=False)
    remaining = dict(updates)
    out: list[str] = []

    for line in lines:
        m = _EXPORT_LINE.match(line)
        if not m or m.group("key") not in remaining:
            out.append(line)
            continue
        key = m.group("key")
        new_value = remaining.pop(key)
        if new_value is None:
            continue
        prefix = line[: line.index(key)]
        out.append(f"{prefix}{key}={_quote(new_value)}")

    added = [k for k in remaining if remaining[k] is not None]
    if added:
        if out and out[-1].strip() != "":
            out.append("")
        for key in added:
            value = remaining[key]
            assert value is not None
            out.append(f"export {key}={_quote(value)}")

    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    return text


def stage_atomic_write(path: str | Path, content: str) -> str:
    """Write ``content`` to a temp file in the same dir as ``path``.

    Returns the temp file path. Caller must finalize via ``os.replace(tmp, path)``
    or delete the temp via ``Path(tmp).unlink()``.
    """
    path = Path(path)
    parent = path.parent if path.parent.exists() else Path(".")
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
    return tmp


def write_env(path: str | Path, updates: dict[str, str | None]) -> None:
    """Build new env content and atomically replace the file in one step."""
    path = Path(path)
    new_text = build_env_text(path, updates)
    tmp = stage_atomic_write(path, new_text)
    try:
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def update_env(path: str | Path, updates: dict[str, str | None]) -> None:
    """Convenience wrapper — read + merge + write."""
    write_env(path, updates)
