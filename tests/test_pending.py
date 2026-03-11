"""Tests for src.summarizer.pending — 待补摘要缓存。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models import SummaryResult
from src.summarizer.pending import (
    insert_summary_into_note,
    load_all_pending,
    remove_pending,
    save_pending,
)


@pytest.fixture()
def pending_dir(tmp_path, monkeypatch):
    """使用临时目录替代 data/pending_summaries/。"""
    d = tmp_path / "pending_summaries"
    monkeypatch.setattr("src.summarizer.pending.PENDING_DIR", d)
    return d


class TestSavePending:
    def test_save_creates_json(self, pending_dir):
        path = save_pending(
            guid="http://example.com/ep1.m4a",
            title="测试标题",
            text="转写文本内容",
            note_path="/vault/Podcasts/test/2026-01-01-测试.md",
            podcast_name="测试播客",
        )
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["guid"] == "http://example.com/ep1.m4a"
        assert data["title"] == "测试标题"
        assert data["text"] == "转写文本内容"
        assert data["note_path"] == "/vault/Podcasts/test/2026-01-01-测试.md"
        assert data["podcast_name"] == "测试播客"

    def test_save_creates_directory(self, pending_dir):
        assert not pending_dir.exists()
        save_pending(guid="g1", title="t1", text="text", note_path="/p")
        assert pending_dir.exists()


class TestLoadAllPending:
    def test_load_empty(self, pending_dir):
        assert load_all_pending() == []

    def test_load_returns_all(self, pending_dir):
        save_pending(guid="g1", title="t1", text="text1", note_path="/p1")
        save_pending(guid="g2", title="t2", text="text2", note_path="/p2")
        results = load_all_pending()
        assert len(results) == 2
        assert all("_filepath" in r for r in results)

    def test_load_skips_corrupted(self, pending_dir):
        save_pending(guid="g1", title="t1", text="text1", note_path="/p1")
        # 写入损坏的 JSON
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / "bad.json").write_text("not json", encoding="utf-8")
        results = load_all_pending()
        assert len(results) == 1


class TestRemovePending:
    def test_remove_deletes_file(self, pending_dir):
        path = save_pending(guid="g1", title="t1", text="text", note_path="/p")
        assert path.exists()
        remove_pending(str(path))
        assert not path.exists()

    def test_remove_nonexistent_no_error(self, pending_dir):
        remove_pending("/nonexistent/file.json")  # 不应抛异常


class TestInsertSummaryIntoNote:
    def _write_note(self, tmp_path: Path, content: str) -> str:
        note = tmp_path / "test_note.md"
        note.write_text(content, encoding="utf-8")
        return str(note)

    def test_insert_before_show_notes(self, tmp_path):
        content = "# Title\n\n> metadata\n\n## Show Notes\n\nsome notes\n\n## 全文转写\n\ntext\n"
        note_path = self._write_note(tmp_path, content)

        summary = SummaryResult(
            summary="这是摘要内容",
            chapters=[{"title": "第一章", "summary": "第一章总结"}],
        )
        result = insert_summary_into_note(note_path, summary)
        assert result is True

        updated = Path(note_path).read_text(encoding="utf-8")
        assert "## AI 摘要" in updated
        assert "这是摘要内容" in updated
        assert "## 章节速览" in updated
        assert "### 第一章" in updated
        # 原有内容保留
        assert "## Show Notes" in updated
        assert "## 全文转写" in updated
        # 摘要在 Show Notes 之前
        assert updated.index("## AI 摘要") < updated.index("## Show Notes")

    def test_insert_before_transcript_if_no_show_notes(self, tmp_path):
        content = "# Title\n\n## 全文转写\n\ntext\n"
        note_path = self._write_note(tmp_path, content)

        summary = SummaryResult(summary="摘要")
        result = insert_summary_into_note(note_path, summary)
        assert result is True

        updated = Path(note_path).read_text(encoding="utf-8")
        assert updated.index("## AI 摘要") < updated.index("## 全文转写")

    def test_insert_summary_only_no_chapters(self, tmp_path):
        content = "# Title\n\n## Show Notes\n\nnotes\n"
        note_path = self._write_note(tmp_path, content)

        summary = SummaryResult(summary="仅摘要无章节")
        result = insert_summary_into_note(note_path, summary)
        assert result is True

        updated = Path(note_path).read_text(encoding="utf-8")
        assert "## AI 摘要" in updated
        assert "## 章节速览" not in updated

    def test_nonexistent_note_returns_false(self):
        result = insert_summary_into_note("/nonexistent/note.md", SummaryResult(summary="s"))
        assert result is False

    def test_no_marker_returns_false(self, tmp_path):
        content = "# Title\n\nsome content without markers\n"
        note_path = self._write_note(tmp_path, content)
        result = insert_summary_into_note(note_path, SummaryResult(summary="s"))
        assert result is False

    def test_empty_summary_returns_false(self, tmp_path):
        content = "# Title\n\n## Show Notes\n\nnotes\n"
        note_path = self._write_note(tmp_path, content)
        result = insert_summary_into_note(note_path, SummaryResult(summary=""))
        assert result is False
