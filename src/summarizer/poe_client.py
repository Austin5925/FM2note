from __future__ import annotations

import json
import re

import httpx
from loguru import logger

from src.models import SummaryResult

SYSTEM_PROMPT = """你是播客内容分析专家。根据播客转写文本，生成：

1. **摘要**（250-500 字，概括核心观点和关键讨论）
2. **章节**（按话题自然分段，每章给出标题和一句话总结）
3. **关键词**（5-10 个核心概念）

严格按以下 JSON 格式输出，不要添加任何其他文字：
{"summary": "...", "chapters": [{"title": "...", "summary": "..."}], "keywords": ["...", "..."]}"""


class PoeSummarizer:
    """通过 Poe API 调用 GPT 模型生成播客摘要。

    Poe API 兼容 OpenAI Chat Completions 格式。
    参考 MacroClaw internal/adapter/poe/client.go 实现。
    """

    BASE_URL = "https://api.poe.com/v1"

    def __init__(
        self,
        api_key: str,
        model: str = "GPT-5.4",
        reasoning_effort: str = "medium",
        cooldown: float = 60.0,
    ):
        self._api_key = api_key
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._cooldown = cooldown
        self._last_call_time: float = 0

    async def summarize(self, text: str, title: str, *, max_retries: int = 3) -> SummaryResult:
        """调用 Poe API 生成播客摘要，带重试。

        Args:
            text: 转写全文
            title: 播客标题
            max_retries: 最大重试次数

        Returns:
            SummaryResult

        Raises:
            Exception: 重试耗尽后仍失败
        """
        import asyncio
        import time

        # 限速：距上次调用不足 cooldown 时等待
        if self._last_call_time > 0 and self._cooldown > 0:
            elapsed = time.monotonic() - self._last_call_time
            if elapsed < self._cooldown:
                wait_time = self._cooldown - elapsed
                logger.info("Poe API 限速等待: {:.0f}s", wait_time)
                await asyncio.sleep(wait_time)

        user_content = f"播客标题：{title}\n\n转写文本：\n{text}"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "reasoning_effort": self._reasoning_effort,
        }

        logger.info(
            "Poe 摘要请求: model={}, reasoning={}, 文本长度={}",
            self._model,
            self._reasoning_effort,
            len(text),
        )

        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=600) as client:
                    resp = await client.post(
                        f"{self.BASE_URL}/chat/completions",
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                    )
                    resp.raise_for_status()
                    api_resp = resp.json()

                content = ""
                choices = api_resp.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")

                if not content:
                    raise ValueError("Poe API 返回空内容")

                self._last_call_time = time.monotonic()
                return self._parse_response(content)

            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning(
                        "Poe 摘要失败 (重试 {}/{}): {}: {}",
                        attempt + 1,
                        max_retries,
                        type(e).__name__,
                        e,
                    )
                    await asyncio.sleep(wait)

        self._last_call_time = time.monotonic()
        raise last_error  # type: ignore[misc]

    def _parse_response(self, content: str) -> SummaryResult:
        """解析 LLM 返回的 JSON 内容，带容错。"""
        # 尝试直接解析
        try:
            data = json.loads(content)
            return self._to_summary_result(data)
        except json.JSONDecodeError:
            pass

        # 容错：提取 JSON 块
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            try:
                data = json.loads(match.group())
                return self._to_summary_result(data)
            except json.JSONDecodeError:
                pass

        logger.warning("Poe 响应 JSON 解析失败，使用原文作为摘要")
        return SummaryResult(summary=content[:500])

    def _to_summary_result(self, data: dict) -> SummaryResult:
        """将解析后的 dict 转为 SummaryResult"""
        chapters = data.get("chapters")
        if chapters and isinstance(chapters, list):
            chapters = [
                {
                    "title": ch.get("title", ""),
                    "summary": ch.get("summary", ""),
                }
                for ch in chapters
                if isinstance(ch, dict)
            ]
        else:
            chapters = None

        raw_kw = data.get("keywords")
        keywords = [str(k) for k in raw_kw] if raw_kw and isinstance(raw_kw, list) else None

        return SummaryResult(
            summary=data.get("summary", ""),
            chapters=chapters,
            keywords=keywords,
        )
