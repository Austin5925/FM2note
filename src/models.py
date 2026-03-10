from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Episode:
    """从 RSS feed 解析出的单集信息"""

    guid: str
    title: str
    podcast_name: str
    pub_date: datetime
    audio_url: str
    duration: str
    show_notes: str
    link: str
    tags: list[str] = field(default_factory=list)
    subtitle_url: str | None = None  # 内置字幕 URL（有则跳过 ASR）


@dataclass
class TranscriptResult:
    """ASR 转写结果"""

    text: str
    paragraphs: list[str]
    summary: str | None = None
    chapters: list[dict] | None = None
    keywords: list[str] | None = None


@dataclass
class ProcessedEpisode:
    """已处理剧集的状态记录"""

    guid: str
    podcast_name: str
    title: str
    status: str  # pending | downloading | transcribing | writing | done | failed
    error_msg: str | None = None
    retry_count: int = 0
    note_path: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
