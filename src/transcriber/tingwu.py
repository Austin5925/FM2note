from __future__ import annotations

import asyncio
import time

import httpx
from loguru import logger

from src.models import TranscriptResult
from src.transcriber.base import TranscriptionError


class TingwuTranscriber:
    """通义听悟 API 转写实现（DashScope SDK）

    通过 dashscope.multimodal.tingwu.TingWu 调用听悟服务。
    认证：DashScope API Key + AppId
    """

    BASE_URL = (
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
        "multimodal-generation/generation"
    )
    MODEL = "tingwu-meeting"

    def __init__(self, api_key: str, app_id: str):
        self._api_key = api_key
        self._app_id = app_id

    @property
    def name(self) -> str:
        return "tingwu"

    async def transcribe(
        self,
        audio_url: str,
        language: str = "cn",
        *,
        poll_interval: int = 30,
        timeout_minutes: int = 180,
    ) -> TranscriptResult:
        """提交音频 URL 到通义听悟，轮询直到完成。

        Args:
            audio_url: 音频文件 URL（直传，无需先下载）
            language: 语言代码
            poll_interval: 轮询间隔（秒）
            timeout_minutes: 最长等待时间（分钟）

        Returns:
            TranscriptResult

        Raises:
            TranscriptionError: 转写失败
        """
        data_id = await self._create_task(audio_url)
        logger.info("通义听悟任务已创建: data_id={}", data_id)

        raw_result = await self._poll_task(data_id, timeout_minutes, poll_interval)
        return await self._parse_result(raw_result)

    async def _create_task(self, audio_url: str) -> str:
        """提交转写任务，返回 dataId"""
        from dashscope.multimodal.tingwu.tingwu import TingWu

        create_input = {
            "task": "createTask",
            "type": "offline",
            "appId": self._app_id,
            "fileUrl": audio_url,
            "phraseId": "",
        }

        response = TingWu.call(
            model=self.MODEL,
            user_defined_input=create_input,
            api_key=self._api_key,
            base_address=self.BASE_URL,
            parameters={},
        )

        output = response.get("output", {}) if isinstance(response, dict) else {}
        data_id = output.get("dataId")
        if not data_id:
            raise TranscriptionError(f"创建任务失败: {response}")

        return data_id

    async def _poll_task(
        self, data_id: str, timeout_minutes: int, interval: int
    ) -> dict:
        """轮询任务状态直到完成或超时"""
        from dashscope.multimodal.tingwu.tingwu import TingWu

        deadline = time.time() + timeout_minutes * 60

        while time.time() < deadline:
            get_input = {"task": "getTask", "dataId": data_id}
            response = TingWu.call(
                model=self.MODEL,
                user_defined_input=get_input,
                api_key=self._api_key,
                base_address=self.BASE_URL,
            )

            output = response.get("output", {}) if isinstance(response, dict) else {}
            status = output.get("taskStatus", "")
            logger.debug("通义听悟任务 {} 状态: {}", data_id, status)

            if status == "COMPLETED":
                return output
            elif status == "FAILED":
                error = output.get("errorMessage", "未知错误")
                raise TranscriptionError(f"通义听悟转写失败: {error}")

            await asyncio.sleep(interval)

        raise TranscriptionError(f"通义听悟转写超时（{timeout_minutes} 分钟）")

    async def _fetch_oss_result(self, url: str) -> dict:
        """从 OSS 签名 URL 获取结果 JSON"""
        async with httpx.AsyncClient(timeout=60) as client:
            for attempt in range(3):
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return resp.json()
                except (httpx.HTTPError, Exception) as e:
                    if attempt == 2:
                        raise TranscriptionError(f"获取 OSS 结果失败: {e}") from e
                    await asyncio.sleep(2**attempt)
        return {}

    async def _parse_result(self, raw_result: dict) -> TranscriptResult:
        """将通义听悟原始响应解析为 TranscriptResult

        DashScope 返回 camelCase 字段名，同时兼容 PascalCase。
        """
        result = raw_result.get("result", raw_result.get("Result", {}))

        # 获取转写结果
        text = ""
        paragraphs = []
        transcription_url = result.get("transcription", result.get("Transcription"))
        if transcription_url:
            trans_data = await self._fetch_oss_result(transcription_url)
            paragraphs_raw = trans_data.get("Transcription", {}).get("Paragraphs", [])
            for para in paragraphs_raw:
                words = para.get("Words", [])
                para_text = "".join(w.get("Text", "") for w in words)
                if para_text.strip():
                    paragraphs.append(para_text.strip())
            text = "\n\n".join(paragraphs)

        # 获取摘要
        summary = None
        summarization_url = result.get("summarization", result.get("Summarization"))
        if summarization_url:
            sum_data = await self._fetch_oss_result(summarization_url)
            paragraph_sum = sum_data.get("Summarization", {}).get("Paragraph", "")
            if paragraph_sum:
                summary = paragraph_sum

        # 获取章节
        chapters = None
        chapters_url = result.get("autoChapters", result.get("AutoChapters"))
        if chapters_url:
            chap_data = await self._fetch_oss_result(chapters_url)
            raw_chapters = chap_data.get("AutoChapters", [])
            if raw_chapters:
                chapters = [
                    {
                        "title": ch.get("Title", ""),
                        "summary": ch.get("Summary", ""),
                    }
                    for ch in raw_chapters
                ]

        return TranscriptResult(
            text=text,
            paragraphs=paragraphs,
            summary=summary,
            chapters=chapters,
        )
