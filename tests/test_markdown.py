from __future__ import annotations

from datetime import datetime

from src.models import Episode, TranscriptResult
from src.writer.markdown import MarkdownGenerator


def _make_episode(**overrides):
    defaults = {
        "guid": "test-guid",
        "title": "测试节目标题",
        "podcast_name": "测试播客",
        "pub_date": datetime(2025, 1, 15, 10, 0, 0),
        "audio_url": "https://example.com/audio.mp3",
        "duration": "01:23:45",
        "show_notes": "这是 show notes 内容",
        "link": "https://www.xiaoyuzhoufm.com/episode/test",
        "tags": ["tech", "ai"],
    }
    defaults.update(overrides)
    return Episode(**defaults)


def _make_transcript(**overrides):
    defaults = {
        "text": "全文转写内容",
        "paragraphs": ["第一段文字", "第二段文字"],
        "summary": None,
        "chapters": None,
    }
    defaults.update(overrides)
    return TranscriptResult(**defaults)


class TestMarkdownGenerator:
    def setup_method(self):
        self.gen = MarkdownGenerator("templates")

    def test_render_basic(self):
        ep = _make_episode()
        tr = _make_transcript()
        result = self.gen.render(ep, tr)

        assert "测试节目标题" in result
        assert "测试播客" in result
        assert "2025-01-15" in result
        assert "01:23:45" in result
        assert "这是 show notes 内容" in result
        assert "第一段文字" in result
        assert "第二段文字" in result

    def test_render_frontmatter(self):
        ep = _make_episode()
        tr = _make_transcript()
        result = self.gen.render(ep, tr)

        assert result.startswith("---")
        assert 'title: "测试节目标题"' in result
        assert 'podcast: "测试播客"' in result
        assert "status: unread" in result
        assert "- tech" in result
        assert "- ai" in result

    def test_render_with_summary(self):
        ep = _make_episode()
        tr = _make_transcript(summary="这是 AI 摘要")
        result = self.gen.render(ep, tr)

        assert "## AI 摘要" in result
        assert "这是 AI 摘要" in result

    def test_render_without_summary(self):
        ep = _make_episode()
        tr = _make_transcript(summary=None)
        result = self.gen.render(ep, tr)

        assert "## AI 摘要" not in result

    def test_render_with_chapters(self):
        ep = _make_episode()
        tr = _make_transcript(
            chapters=[
                {"title": "第一章", "summary": "章节一摘要"},
                {"title": "第二章", "summary": "章节二摘要"},
            ]
        )
        result = self.gen.render(ep, tr)

        assert "## 章节速览" in result
        assert "### 第一章" in result
        assert "章节一摘要" in result

    def test_render_version(self):
        ep = _make_episode()
        tr = _make_transcript()
        result = self.gen.render(ep, tr)

        assert "FM2note v" in result

    def test_render_link(self):
        ep = _make_episode()
        tr = _make_transcript()
        result = self.gen.render(ep, tr)

        assert "[小宇宙](https://www.xiaoyuzhoufm.com/episode/test)" in result

    def test_render_with_keywords(self):
        ep = _make_episode()
        tr = _make_transcript(keywords=["人工智能", "播客"])
        result = self.gen.render(ep, tr)

        # 关键词只出现在 frontmatter tags 中，不再单独渲染章节
        assert "  - 人工智能" in result
        assert "  - 播客" in result
        assert "## 关键词" not in result

    def test_render_html_show_notes_cleaned(self):
        ep = _make_episode(show_notes="<p>这是 <b>HTML</b> 格式</p>")
        tr = _make_transcript()
        result = self.gen.render(ep, tr)

        assert "这是" in result
        assert "<p>" not in result
        assert "<b>" not in result

    def test_render_asr_engine(self):
        ep = _make_episode()
        tr = _make_transcript()
        result = self.gen.render(ep, tr, asr_engine="bailian")

        assert 'asr_engine: "bailian"' in result

    def test_render_subtitle_engine(self):
        ep = _make_episode()
        tr = _make_transcript()
        result = self.gen.render(ep, tr, asr_engine="subtitle")

        assert 'asr_engine: "subtitle"' in result
