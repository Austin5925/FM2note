from datetime import datetime

from src.models import Episode, ProcessedEpisode, TranscriptResult


class TestEpisode:
    def test_create_episode(self):
        ep = Episode(
            guid="test-guid-123",
            title="测试节目",
            podcast_name="测试播客",
            pub_date=datetime(2025, 1, 15),
            audio_url="https://example.com/audio.mp3",
            duration="01:23:45",
            show_notes="这是 show notes",
            link="https://www.xiaoyuzhoufm.com/episode/test",
        )
        assert ep.guid == "test-guid-123"
        assert ep.title == "测试节目"
        assert ep.tags == []

    def test_episode_with_tags(self):
        ep = Episode(
            guid="g1",
            title="t1",
            podcast_name="p1",
            pub_date=datetime(2025, 1, 1),
            audio_url="https://example.com/a.mp3",
            duration="00:30:00",
            show_notes="",
            link="https://example.com",
            tags=["tech", "ai"],
        )
        assert ep.tags == ["tech", "ai"]


class TestTranscriptResult:
    def test_create_minimal(self):
        tr = TranscriptResult(text="全文文本", paragraphs=["段落1", "段落2"])
        assert tr.text == "全文文本"
        assert len(tr.paragraphs) == 2
        assert tr.summary is None
        assert tr.chapters is None
        assert tr.keywords is None

    def test_create_full(self):
        tr = TranscriptResult(
            text="全文",
            paragraphs=["p1"],
            summary="摘要内容",
            chapters=[{"title": "第一章", "summary": "概述"}],
            keywords=["AI", "播客"],
        )
        assert tr.summary == "摘要内容"
        assert len(tr.chapters) == 1
        assert tr.keywords == ["AI", "播客"]


class TestProcessedEpisode:
    def test_create_with_defaults(self):
        pe = ProcessedEpisode(
            guid="g1",
            podcast_name="p1",
            title="t1",
            status="pending",
        )
        assert pe.status == "pending"
        assert pe.error_msg is None
        assert pe.retry_count == 0
        assert pe.note_path is None
        assert isinstance(pe.created_at, datetime)

    def test_create_failed(self):
        pe = ProcessedEpisode(
            guid="g1",
            podcast_name="p1",
            title="t1",
            status="failed",
            error_msg="转写超时",
            retry_count=2,
        )
        assert pe.status == "failed"
        assert pe.error_msg == "转写超时"
        assert pe.retry_count == 2
