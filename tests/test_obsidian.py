from __future__ import annotations

from datetime import datetime

import pytest

from src.models import Episode
from src.writer.obsidian import ObsidianWriter


def _make_episode(**overrides):
    defaults = {
        "guid": "test-guid",
        "title": "测试节目",
        "podcast_name": "测试播客",
        "pub_date": datetime(2025, 1, 15),
        "audio_url": "https://example.com/audio.mp3",
        "duration": "01:00:00",
        "show_notes": "",
        "link": "https://example.com",
    }
    defaults.update(overrides)
    return Episode(**defaults)


class TestObsidianWriter:
    def test_write_note(self, tmp_path):
        writer = ObsidianWriter(str(tmp_path), "Podcasts")
        ep = _make_episode()
        content = "# 测试笔记\n\n这是内容"

        path = writer.write_note(ep, content)

        assert path.exists()
        assert path.read_text(encoding="utf-8") == content
        assert "Podcasts" in str(path)
        assert "测试播客" in str(path)
        assert "2025-01-15" in path.name

    def test_write_note_creates_directories(self, tmp_path):
        writer = ObsidianWriter(str(tmp_path), "Podcasts")
        ep = _make_episode(podcast_name="深层子目录")
        content = "内容"

        path = writer.write_note(ep, content)
        assert path.exists()
        assert "深层子目录" in str(path)

    def test_write_note_raises_on_duplicate(self, tmp_path):
        writer = ObsidianWriter(str(tmp_path), "Podcasts")
        ep = _make_episode()
        writer.write_note(ep, "first")

        with pytest.raises(FileExistsError, match="笔记已存在"):
            writer.write_note(ep, "second")

    def test_note_exists(self, tmp_path):
        writer = ObsidianWriter(str(tmp_path), "Podcasts")
        ep = _make_episode()

        assert writer.note_exists(ep) is False
        writer.write_note(ep, "content")
        assert writer.note_exists(ep) is True

    def test_sanitize_filename(self, tmp_path):
        writer = ObsidianWriter(str(tmp_path))
        assert writer._sanitize_filename('test/file:name*"bad"') == "testfilenamebad"
        assert writer._sanitize_filename("正常文件名") == "正常文件名"
        assert writer._sanitize_filename("   ") == "untitled"
        assert writer._sanitize_filename("") == "untitled"

    def test_sanitize_long_filename(self, tmp_path):
        writer = ObsidianWriter(str(tmp_path))
        long_name = "a" * 300
        result = writer._sanitize_filename(long_name)
        assert len(result) == 200

    def test_write_note_with_special_chars_in_title(self, tmp_path):
        writer = ObsidianWriter(str(tmp_path), "Podcasts")
        ep = _make_episode(title='EP01: "如何/为什么?" | 特别篇')
        content = "内容"

        path = writer.write_note(ep, content)
        assert path.exists()
        assert '"' not in path.name
        assert "/" not in path.name
