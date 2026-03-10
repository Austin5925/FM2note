from __future__ import annotations

import asyncio
import time
import uuid

import httpx
from loguru import logger

from src.models import TranscriptResult
from src.transcriber.base import TranscriptionError


class TingwuTranscriber:
    """通义听悟 API 转写实现

    API 版本：2023-09-30
    域名：tingwu.cn-beijing.aliyuncs.com
    认证：阿里云 AccessKey + AppKey
    """

    ENDPOINT = "https://tingwu.cn-beijing.aliyuncs.com"
    API_VERSION = "2023-09-30"

    def __init__(
        self,
        access_key_id: str,
        access_key_secret: str,
        app_key: str,
    ):
        self._access_key_id = access_key_id
        self._access_key_secret = access_key_secret
        self._app_key = app_key

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
        task_body = self._build_task_body(audio_url, language)
        task_id = await self._create_task(task_body)
        logger.info("通义听悟任务已创建: task_id={}", task_id)

        raw_result = await self._poll_task(task_id, timeout_minutes, poll_interval)
        return await self._parse_result(raw_result)

    def _build_task_body(self, audio_url: str, language: str) -> dict:
        """构建 CreateTask 请求体"""
        task_key = f"fm2note-{uuid.uuid4().hex[:12]}"
        return {
            "AppKey": self._app_key,
            "Input": {
                "FileUrl": audio_url,
                "SourceLanguage": language,
                "TaskKey": task_key,
            },
            "Parameters": {
                "Transcription": {
                    "DiarizationEnabled": True,
                },
                "Summarization": {
                    "Enabled": True,
                    "Types": ["Paragraph", "QuestionsAnswering", "MindMap"],
                },
                "AutoChapters": {
                    "Enabled": True,
                },
            },
        }

    async def _create_task(self, body: dict) -> str:
        """提交转写任务，返回 TaskId"""
        from alibabacloud_tea_openapi.models import Config
        from alibabacloud_tingwu20230930.client import Client
        from alibabacloud_tingwu20230930.models import CreateTaskRequest

        config = Config(
            access_key_id=self._access_key_id,
            access_key_secret=self._access_key_secret,
            endpoint=self.ENDPOINT,
        )
        client = Client(config)

        request = CreateTaskRequest(
            type="offline",
            body=body,
        )

        response = client.create_task(request)
        result = response.body

        if not result or not result.get("Data", {}).get("TaskId"):
            raise TranscriptionError(f"创建任务失败: {result}")

        return result["Data"]["TaskId"]

    async def _poll_task(
        self, task_id: str, timeout_minutes: int, interval: int
    ) -> dict:
        """轮询任务状态直到完成或超时"""
        from alibabacloud_tea_openapi.models import Config
        from alibabacloud_tingwu20230930.client import Client
        from alibabacloud_tingwu20230930.models import GetTaskInfoRequest

        config = Config(
            access_key_id=self._access_key_id,
            access_key_secret=self._access_key_secret,
            endpoint=self.ENDPOINT,
        )
        client = Client(config)

        deadline = time.time() + timeout_minutes * 60

        while time.time() < deadline:
            request = GetTaskInfoRequest(task_id=task_id)
            response = client.get_task_info(request)
            result = response.body

            status = result.get("Data", {}).get("TaskStatus", "")
            logger.debug("通义听悟任务 {} 状态: {}", task_id, status)

            if status == "COMPLETED":
                return result["Data"]
            elif status == "FAILED":
                error = result.get("Data", {}).get("ErrorMessage", "未知错误")
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
        """将通义听悟原始响应解析为 TranscriptResult"""
        result = raw_result.get("Result", {})

        # 获取转写结果
        text = ""
        paragraphs = []
        transcription_url = result.get("Transcription")
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
        summarization_url = result.get("Summarization")
        if summarization_url:
            sum_data = await self._fetch_oss_result(summarization_url)
            paragraph_sum = sum_data.get("Summarization", {}).get("Paragraph", "")
            if paragraph_sum:
                summary = paragraph_sum

        # 获取章节
        chapters = None
        chapters_url = result.get("AutoChapters")
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
