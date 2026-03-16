from __future__ import annotations

import json
import re

import httpx
from loguru import logger

from src.models import SummaryResult

SYSTEM_PROMPT = """You are a podcast content analyst. Given a podcast transcript, generate:

1. **Summary** (250-500 words, covering core viewpoints and key discussions)
2. **Chapters** (natural topic segments, each with a title and one-sentence summary)
3. **Keywords** (5-10 core concepts)

Output ONLY valid JSON in this exact format, no other text:
{"summary": "...", "chapters": [{"title": "...", "summary": "..."}], "keywords": ["...", "..."]}"""


class OpenAISummarizer:
    """OpenAI-compatible API summarizer.

    Works with OpenAI, DeepSeek, Groq, Ollama, and any OpenAI-compatible endpoint.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        cooldown: float = 0,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._cooldown = cooldown
        self._last_call_time: float = 0

    @property
    def name(self) -> str:
        return f"openai/{self._model}"

    async def summarize(self, text: str, title: str, *, max_retries: int = 3) -> SummaryResult:
        """Call OpenAI-compatible API to generate podcast summary.

        Args:
            text: Full transcript text.
            title: Podcast episode title.
            max_retries: Maximum retry attempts.

        Returns:
            SummaryResult with summary, chapters, and keywords.

        Raises:
            Exception: After all retries exhausted.
        """
        import asyncio
        import time

        if self._last_call_time > 0 and self._cooldown > 0:
            elapsed = time.monotonic() - self._last_call_time
            if elapsed < self._cooldown:
                wait_time = self._cooldown - elapsed
                logger.info("OpenAI API rate limit wait: {:.0f}s", wait_time)
                await asyncio.sleep(wait_time)

        # Truncate very long transcripts to avoid exceeding API context limits
        max_chars = 80000
        if len(text) > max_chars:
            logger.warning("Transcript truncated for summary: {} → {} chars", len(text), max_chars)
            text = text[:max_chars]

        user_content = f"Podcast title: {title}\n\nTranscript:\n{text}"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
        }

        logger.info(
            "OpenAI summary request: model={}, text_length={}",
            self._model,
            len(text),
        )

        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=600) as client:
                    resp = await client.post(
                        f"{self._base_url}/chat/completions",
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
                    raise ValueError("OpenAI API returned empty content")

                self._last_call_time = time.monotonic()
                return self._parse_response(content)

            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning(
                        "OpenAI summary failed (retry {}/{}): {}: {}",
                        attempt + 1,
                        max_retries,
                        type(e).__name__,
                        e,
                    )
                    await asyncio.sleep(wait)

        self._last_call_time = time.monotonic()
        raise last_error  # type: ignore[misc]

    def _parse_response(self, content: str) -> SummaryResult:
        """Parse LLM JSON response with fallback."""
        try:
            data = json.loads(content)
            return self._to_summary_result(data)
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            try:
                data = json.loads(match.group())
                return self._to_summary_result(data)
            except json.JSONDecodeError:
                pass

        logger.warning("OpenAI response JSON parse failed, using raw text as summary")
        return SummaryResult(summary=content[:500])

    def _to_summary_result(self, data: dict) -> SummaryResult:
        """Convert parsed dict to SummaryResult."""
        chapters = data.get("chapters")
        if chapters and isinstance(chapters, list):
            chapters = [
                {"title": ch.get("title", ""), "summary": ch.get("summary", "")}
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
