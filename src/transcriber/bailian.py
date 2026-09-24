from __future__ import annotations

import asyncio
import time

import httpx
from loguru import logger

from src.models import TranscriptResult
from src.transcriber.base import TranscriptionError

DEFAULT_BAILIAN_MODEL = "qwen-audio-3.1-asr-flash-filetrans"
BAILIAN_ASR_MODELS = (
    DEFAULT_BAILIAN_MODEL,
    "qwen3-asr-flash-filetrans",
    "qwen-audio-3.0-asr-flash-filetrans",
)


class BailianTranscriber:
    """阿里云百炼 ASR 转写实现

    使用 DashScope SDK，默认模型 qwen-audio-3.1-asr-flash-filetrans
    最长 12 小时 / 2GB
    """

    def __init__(self, api_key: str, model: str = DEFAULT_BAILIAN_MODEL):
        self._api_key = api_key
        self.model = model

    @property
    def name(self) -> str:
        return "bailian"

    async def transcribe(
        self,
        audio_url: str,
        language: str = "cn",
        *,
        poll_interval: int = 2,
        timeout_minutes: int = 180,
    ) -> TranscriptResult:
        """使用百炼 ASR 转写音频。

        Args:
            audio_url: 音频文件 URL
            language: 语言代码
            poll_interval: 轮询间隔（秒）
            timeout_minutes: 最长等待时间（分钟）

        Returns:
            TranscriptResult（不含摘要和章节）

        Raises:
            TranscriptionError: 转写失败
        """
        from dashscope.audio.asr import Transcription

        # 提交异步转写任务
        try:
            response = await asyncio.to_thread(
                Transcription.async_call,
                model=self.model,
                file_urls=[audio_url],
                api_key=self._api_key,
                channel_id=[0],
                language_hints=["zh", "en"] if language == "cn" else [language],
            )
        except Exception as e:
            raise TranscriptionError(f"百炼 ASR 提交任务失败: {e}") from e

        output = getattr(response, "output", None) or {}
        task_id = output.get("task_id")
        if not task_id:
            raise TranscriptionError(
                f"百炼 ASR 未返回 task_id (status={getattr(response, 'status_code', '?')})"
            )

        logger.info("百炼 ASR 任务已创建: task_id={}", task_id)

        # 轮询等待完成
        deadline = time.time() + timeout_minutes * 60
        while time.time() < deadline:
            result = await asyncio.to_thread(Transcription.fetch, task_id, api_key=self._api_key)
            output = getattr(result, "output", None) or {}
            status = output.get("task_status", "")
            logger.debug("百炼 ASR 任务 {} 状态: {}", task_id, status)

            if status == "SUCCEEDED":
                return await self._parse_result(result)
            elif status == "FAILED":
                error = output.get("message", "未知错误")
                raise TranscriptionError(f"百炼 ASR 转写失败: {error}")

            await asyncio.sleep(poll_interval)

        raise TranscriptionError(f"百炼 ASR 转写超时（{timeout_minutes} 分钟）")

    async def _parse_result(self, result) -> TranscriptResult:
        """解析百炼 ASR 结果"""
        results = result.output.get("results", [])
        if not results:
            raise TranscriptionError("百炼 ASR 返回结果为空")

        transcription_url = results[0].get("transcription_url")
        if not transcription_url:
            raise TranscriptionError("百炼 ASR 未返回 transcription_url")

        # 获取转写 JSON
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(transcription_url)
            resp.raise_for_status()
            trans_data = resp.json()

        # 解析
        transcripts = trans_data.get("transcripts", [])
        if not transcripts:
            return TranscriptResult(text="", paragraphs=[])

        full_text = transcripts[0].get("text", "")
        sentences = transcripts[0].get("sentences", [])

        # 按句子分组为段落（每 5 句一段）
        paragraphs = []
        chunk: list[str] = []
        for sent in sentences:
            chunk.append(sent.get("text", ""))
            if len(chunk) >= 5:
                paragraphs.append("".join(chunk))
                chunk = []
        if chunk:
            paragraphs.append("".join(chunk))

        if not paragraphs:
            paragraphs = [full_text]

        return TranscriptResult(
            text=full_text,
            paragraphs=paragraphs,
            summary=None,  # 百炼 ASR 不含摘要
            chapters=None,
            keywords=None,
        )
