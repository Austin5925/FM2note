from __future__ import annotations

import asyncio
from http import HTTPStatus

import httpx
from loguru import logger

from src.models import TranscriptResult
from src.transcriber.base import TranscriptionError


class FunASRTranscriber:
    """FunASR 录音文件识别实现（DashScope SDK）

    纯转写，不含摘要/章节/关键词。
    认证：仅 DASHSCOPE_API_KEY（无需 AppId）。
    支持模型轮换：当某个模型免费额度用尽（403）时自动切换到下一个。
    """

    MODEL = "fun-asr"

    # 同代模型变体，免费额度独立计算，用于轮换
    FALLBACK_MODELS = [
        "fun-asr",
        "fun-asr-2025-11-07",
        "fun-asr-2025-08-25",
        "fun-asr-mtl",
        "fun-asr-mtl-2025-08-25",
    ]

    def __init__(self, api_key: str, model: str | None = None):
        self._api_key = api_key
        if model:
            self.MODEL = model

    @property
    def name(self) -> str:
        return "funasr"

    async def transcribe(
        self,
        audio_url: str,
        language: str = "cn",
        *,
        timeout_minutes: int = 180,
    ) -> TranscriptResult:
        """提交音频 URL 到 FunASR，等待完成并返回转写结果。

        当某个模型免费额度用尽（403 AllocationQuota）时，
        自动尝试 FALLBACK_MODELS 中的下一个模型。

        Args:
            audio_url: 音频文件 URL
            language: 语言代码（cn/en）
            timeout_minutes: 最长等待时间（分钟）

        Returns:
            TranscriptResult（summary/chapters/keywords 为 None）

        Raises:
            TranscriptionError: 转写失败
        """
        import dashscope
        from dashscope.audio.asr import Transcription

        dashscope.api_key = self._api_key

        lang_hints = ["zh", "en"] if language == "cn" else [language]

        # 构建尝试列表：优先用配置的模型，然后按 fallback 顺序
        models = [self.MODEL] + [m for m in self.FALLBACK_MODELS if m != self.MODEL]

        task_response = None
        used_model = self.MODEL
        for model in models:
            logger.info("FunASR 提交任务: model={}, url={}", model, audio_url[:80])
            task_response = Transcription.async_call(
                model=model,
                file_urls=[audio_url],
                language_hints=lang_hints,
            )

            if task_response.status_code == 403:
                logger.warning("模型 {} 免费额度已用尽，尝试下一个", model)
                continue

            if task_response.status_code != HTTPStatus.OK:
                raise TranscriptionError(
                    f"FunASR 提交任务失败: {task_response.status_code} {task_response.message}"
                )

            used_model = model
            break
        else:
            raise TranscriptionError("所有 FunASR 模型免费额度已用尽，请充值或关闭用完即停")

        task_id = task_response.output.task_id
        logger.info("FunASR 任务已创建: model={}, task_id={}", used_model, task_id)

        # 等待结果（SDK 内置轮询）
        result = await asyncio.to_thread(Transcription.wait, task=task_id)

        if result.status_code != HTTPStatus.OK:
            raise TranscriptionError(f"FunASR 转写失败: {result.status_code} {result.message}")

        return await self._parse_results(result.output)

    async def _parse_results(self, output: dict) -> TranscriptResult:
        """解析 FunASR 输出，获取 transcription_url 并提取文本"""
        results = getattr(output, "results", None) or output.get("results", [])
        if not results:
            raise TranscriptionError("FunASR 返回空结果")

        first = results[0]
        status = first.get("subtask_status", "")
        if status != "SUCCEEDED":
            raise TranscriptionError(f"FunASR 子任务失败: {status}")

        transcription_url = first.get("transcription_url", "")
        if not transcription_url:
            raise TranscriptionError("FunASR 未返回 transcription_url")

        return await self._fetch_and_parse(transcription_url)

    async def _fetch_and_parse(self, url: str) -> TranscriptResult:
        """从 transcription_url 获取 JSON 并解析为 TranscriptResult"""
        async with httpx.AsyncClient(timeout=60) as client:
            for attempt in range(3):
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except (httpx.HTTPError, Exception) as e:
                    if attempt == 2:
                        raise TranscriptionError(f"获取 FunASR 结果失败: {e}") from e
                    await asyncio.sleep(2**attempt)

        transcripts = data.get("transcripts", [])
        if not transcripts:
            raise TranscriptionError("FunASR transcripts 为空")

        first_channel = transcripts[0]
        full_text = first_channel.get("text", "")
        sentences = first_channel.get("sentences", [])

        # 从 sentences 拼合段落：每 5 句或遇到长停顿时切段
        paragraphs = self._sentences_to_paragraphs(sentences)

        logger.info(
            "FunASR 转写完成: {} 字, {} 段",
            len(full_text),
            len(paragraphs),
        )

        return TranscriptResult(
            text=full_text,
            paragraphs=paragraphs,
            summary=None,
            chapters=None,
            keywords=None,
        )

    def _sentences_to_paragraphs(
        self,
        sentences: list[dict],
        max_sentences: int = 5,
        gap_threshold_ms: int = 2000,
    ) -> list[str]:
        """将 sentences 按句数和时间间隔拼合为段落。

        Args:
            sentences: FunASR 返回的 sentences 列表
            max_sentences: 每段最大句数
            gap_threshold_ms: 句间停顿超过此值则切段（毫秒）
        """
        if not sentences:
            return []

        paragraphs = []
        current: list[str] = []
        count = 0
        prev_end = 0

        for sent in sentences:
            text = sent.get("text", "").strip()
            if not text:
                continue

            begin = sent.get("begin_time", 0)
            gap = begin - prev_end if prev_end > 0 else 0

            if current and (count >= max_sentences or gap > gap_threshold_ms):
                paragraphs.append("".join(current))
                current = []
                count = 0

            current.append(text)
            count += 1
            prev_end = sent.get("end_time", 0)

        if current:
            paragraphs.append("".join(current))

        return paragraphs


class ParaformerTranscriber(FunASRTranscriber):
    """Paraformer 录音文件识别（更便宜的 ASR 选项）"""

    MODEL = "paraformer-v2"
    FALLBACK_MODELS = []  # Paraformer 无多版本轮换

    @property
    def name(self) -> str:
        return "paraformer"
