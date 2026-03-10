from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.models import TranscriptResult


class TranscriptionError(Exception):
    """转写过程中的错误"""


@runtime_checkable
class Transcriber(Protocol):
    """所有 ASR 引擎必须实现此协议"""

    async def transcribe(self, audio_url: str, language: str = "cn") -> TranscriptResult:
        """提交音频并返回转写结果（阻塞直到完成）"""
        ...

    @property
    def name(self) -> str:
        """引擎名称，用于日志和报告"""
        ...
