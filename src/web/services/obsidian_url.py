"""Compute obsidian:// deep links from absolute note paths.

Shared by the transcribe + history routes so both surfaces use one canonical
implementation (history previously had a JS-side computation, which broke
inside PyWebView's WebKit because ``window.location.href`` doesn't hand off
custom URL schemes — only ``<a target="_blank">`` does).
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote


def build_obsidian_url(vault_path: str, note_path) -> str:
    """Return an ``obsidian://`` deep link for ``note_path`` inside ``vault_path``.

    Returns ``""`` if the note doesn't live under the vault (which indicates
    a configuration mismatch).
    """
    if not vault_path or not note_path:
        return ""
    vault = Path(vault_path).expanduser().resolve()
    note = Path(note_path).expanduser().resolve()
    try:
        rel = note.relative_to(vault).with_suffix("")
    except ValueError:
        return ""
    return f"obsidian://open?vault={quote(vault.name)}&file={quote(str(rel))}"
