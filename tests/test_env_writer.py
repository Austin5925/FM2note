"""Tests for the .env round-trip writer."""

from __future__ import annotations

from pathlib import Path

from src.web.services.env_writer import read_env, write_env


def test_read_simple_unquoted(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("export FOO=bar\nBAZ=qux\n", encoding="utf-8")
    assert read_env(p) == {"FOO": "bar", "BAZ": "qux"}


def test_read_quoted_values(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("export A=\"hello world\"\nB='q'\n", encoding="utf-8")
    out = read_env(p)
    assert out["A"] == "hello world"
    assert out["B"] == "q"


def test_read_ignores_comments_and_blanks(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("# comment\n\nexport X=1\n  # another\n", encoding="utf-8")
    assert read_env(p) == {"X": "1"}


def test_read_strips_inline_comment_for_unquoted(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("export X=1 # trailing\n", encoding="utf-8")
    assert read_env(p) == {"X": "1"}


def test_write_preserves_comments_and_order(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text(
        "# Header comment\nexport FOO=old\n\n# section\nexport BAR=keep\n",
        encoding="utf-8",
    )
    write_env(p, {"FOO": "new"})
    text = p.read_text(encoding="utf-8")
    assert "# Header comment" in text
    assert "# section" in text
    assert "FOO=new" in text
    assert "BAR=keep" in text
    assert "FOO=old" not in text


def test_write_appends_new_key(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("export FOO=1\n", encoding="utf-8")
    write_env(p, {"NEW": "value"})
    assert read_env(p) == {"FOO": "1", "NEW": "value"}


def test_write_deletes_with_none(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("export FOO=1\nexport BAR=2\n", encoding="utf-8")
    write_env(p, {"FOO": None})
    assert read_env(p) == {"BAR": "2"}


def test_write_handles_empty_value(tmp_path: Path):
    p = tmp_path / ".env"
    write_env(p, {"FOO": ""})
    text = p.read_text(encoding="utf-8")
    assert 'FOO=""' in text
    assert read_env(p) == {"FOO": ""}


def test_write_quotes_when_special_chars(tmp_path: Path):
    p = tmp_path / ".env"
    write_env(p, {"FOO": "hello world"})
    text = p.read_text(encoding="utf-8")
    assert 'FOO="hello world"' in text
    assert read_env(p) == {"FOO": "hello world"}


def test_write_escapes_quotes_in_value(tmp_path: Path):
    p = tmp_path / ".env"
    write_env(p, {"FOO": 'a"b'})
    assert read_env(p)["FOO"] == 'a"b'


def test_write_creates_file_if_missing(tmp_path: Path):
    p = tmp_path / ".env"
    assert not p.exists()
    write_env(p, {"FOO": "1"})
    assert p.exists()
    assert read_env(p) == {"FOO": "1"}


def test_write_is_atomic_no_partial_file(tmp_path: Path, monkeypatch):
    """If os.replace fails, the original file is left untouched."""
    p = tmp_path / ".env"
    p.write_text("export FOO=orig\n", encoding="utf-8")

    import src.web.services.env_writer as ew

    def boom(*a, **kw):
        raise OSError("disk full")

    import contextlib

    monkeypatch.setattr(ew.os, "replace", boom)
    with contextlib.suppress(OSError):
        ew.write_env(p, {"FOO": "new"})
    # Original preserved
    assert read_env(p) == {"FOO": "orig"}
    # No stray temp files
    stray = [
        f.name
        for f in tmp_path.iterdir()
        if f.is_file() and f.name.startswith(".env.") and f.name != ".env"
    ]
    assert stray == []
