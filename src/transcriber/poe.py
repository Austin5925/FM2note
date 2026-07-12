from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from loguru import logger

from src.models import TranscriptResult
from src.transcriber.base import TranscriptionError

DEFAULT_POE_ASR_MODEL = "qwen3.5-omni-flash"
POE_ASR_MODELS = (
    DEFAULT_POE_ASR_MODEL,
    "qwen3.5-omni-plus",
)


class PoeTranscriber:
    """Poe file-attachment transcription using Qwen3.5 Omni.

    Poe's OpenAI-compatible endpoint ignores the native ``audio`` request
    field. Audio must instead be sent as a base64 ``type=file`` attachment.
    The response is the normal Chat Completions text shape.
    """

    BASE_URL = "https://api.poe.com/v1"
    MAX_AUDIO_BYTES = 200 * 1024 * 1024
    MAX_OUTPUT_TOKENS = 64_000
    RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 529})
    MAX_ATTEMPTS = 3

    _ZH_PROMPT = (
        "请完整逐字转写整段音频，从开头一直到最后一句。只输出原语言的转写文字，"
        "不要翻译、总结、解释、添加标题或时间戳。保留数字、英文、专有名词、重复和口头语；"
        "根据自然停顿合理分段。"
    )
    _OTHER_PROMPT = (
        "Transcribe the entire audio verbatim from beginning to end. Output only the "
        "transcript in the original spoken language. Do not translate, summarize, explain, "
        "add headings, or add timestamps. Preserve numbers, names, repetitions, and fillers, "
        "and use natural paragraph breaks."
    )

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_POE_ASR_MODEL,
        temp_dir: str = "./data/tmp",
    ):
        if model not in POE_ASR_MODELS:
            allowed = ", ".join(POE_ASR_MODELS)
            raise TranscriptionError(f"不支持的 Poe 转写模型: {model}（可选: {allowed}）")
        self._api_key = api_key
        self._model = model
        self._temp_dir = Path(temp_dir)
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return f"poe/{self._model}"

    @property
    def model(self) -> str:
        return self._model

    async def transcribe(self, audio_url: str, language: str = "cn") -> TranscriptResult:
        """Download an audio URL, upload it to Poe, and return the text transcript."""
        audio_path: Path | None = None
        try:
            audio_path, mime_type = await self._download_audio(audio_url)
            return await self._transcribe_file(audio_path, mime_type, language)
        finally:
            if audio_path is not None:
                audio_path.unlink(missing_ok=True)

    async def _download_audio(self, url: str) -> tuple[Path, str]:
        suffix = self._safe_suffix(url)
        fd, raw_path = tempfile.mkstemp(prefix="poe-asr-", suffix=suffix, dir=self._temp_dir)
        os.close(fd)
        path = Path(raw_path)
        succeeded = False

        timeout = httpx.Timeout(600, connect=30, read=180, write=60, pool=30)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                for attempt in range(self.MAX_ATTEMPTS):
                    try:
                        async with client.stream("GET", url) as response:
                            if (
                                response.status_code in self.RETRYABLE_STATUS_CODES
                                and attempt + 1 < self.MAX_ATTEMPTS
                            ):
                                await response.aread()
                                await self._retry_delay(response, attempt)
                                continue
                            response.raise_for_status()
                            mime_type = self._resolve_mime_type(
                                response.headers.get("content-type", ""), suffix
                            )
                            declared_size = self._content_length(response)
                            if declared_size is not None and declared_size > self.MAX_AUDIO_BYTES:
                                raise TranscriptionError(
                                    "音频文件超过 Poe 转写上限 "
                                    f"({declared_size / 1024 / 1024:.1f}MB > "
                                    f"{self.MAX_AUDIO_BYTES / 1024 / 1024:.0f}MB)"
                                )

                            written = 0
                            with path.open("wb") as output:
                                async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                                    written += len(chunk)
                                    if written > self.MAX_AUDIO_BYTES:
                                        raise TranscriptionError(
                                            "音频文件超过 Poe 转写上限 "
                                            f"({self.MAX_AUDIO_BYTES / 1024 / 1024:.0f}MB)"
                                        )
                                    output.write(chunk)
                            if written == 0:
                                raise TranscriptionError("音频下载结果为空")
                            logger.info(
                                "Poe 音频下载完成: {:.1f}MB, model={}",
                                written / 1024 / 1024,
                                self._model,
                            )
                            succeeded = True
                            return path, mime_type
                    except TranscriptionError:
                        raise
                    except (httpx.TimeoutException, httpx.TransportError) as exc:
                        if attempt + 1 >= self.MAX_ATTEMPTS:
                            raise TranscriptionError(f"下载音频失败: {type(exc).__name__}") from exc
                        await asyncio.sleep(2**attempt)
                    except httpx.HTTPStatusError as exc:
                        raise TranscriptionError(
                            f"下载音频失败: HTTP {exc.response.status_code}"
                        ) from exc
        finally:
            if not succeeded:
                path.unlink(missing_ok=True)

        raise TranscriptionError("下载音频失败")  # pragma: no cover

    async def _transcribe_file(
        self,
        audio_path: Path,
        mime_type: str,
        language: str,
    ) -> TranscriptResult:
        encoded = await asyncio.to_thread(self._encode_audio, audio_path)
        payload = self._build_payload(audio_path.name, mime_type, encoded, language)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "X-Title": "FM2note",
        }
        timeout = httpx.Timeout(900, connect=30, read=900, write=300, pool=30)

        async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
            for attempt in range(self.MAX_ATTEMPTS):
                try:
                    response = await client.post(f"{self.BASE_URL}/chat/completions", json=payload)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    if attempt + 1 >= self.MAX_ATTEMPTS:
                        raise TranscriptionError(f"Poe 转写请求失败: {type(exc).__name__}") from exc
                    await asyncio.sleep(2**attempt)
                    continue

                if (
                    response.status_code in self.RETRYABLE_STATUS_CODES
                    and attempt + 1 < self.MAX_ATTEMPTS
                ):
                    await self._retry_delay(response, attempt)
                    continue
                if response.status_code != 200:
                    raise self._http_error(response)

                try:
                    body = response.json()
                except ValueError as exc:
                    raise TranscriptionError("Poe 转写返回了无效 JSON") from exc
                result = self._parse_response(body)
                logger.info(
                    "Poe 转写完成: model={}, {} 字, {} 段",
                    self._model,
                    len(result.text),
                    len(result.paragraphs),
                )
                return result

        raise TranscriptionError("Poe 转写重试耗尽")  # pragma: no cover

    def _build_payload(
        self,
        filename: str,
        mime_type: str,
        encoded_audio: str,
        language: str,
    ) -> dict:
        prompt = self._ZH_PROMPT if language in {"cn", "zh", "zh-CN"} else self._OTHER_PROMPT
        return {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "file",
                            "file": {
                                "filename": filename,
                                "file_data": f"data:{mime_type};base64,{encoded_audio}",
                            },
                        },
                    ],
                }
            ],
            "stream": False,
            "temperature": 0,
            "max_tokens": self.MAX_OUTPUT_TOKENS,
            "output_mode": "text",
        }

    def _parse_response(self, body: dict) -> TranscriptResult:
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise TranscriptionError("Poe 转写响应缺少 choices")

        first = choices[0]
        if not isinstance(first, dict):
            raise TranscriptionError("Poe 转写响应 choices 格式错误")
        finish_reason = first.get("finish_reason")
        if finish_reason == "length":
            raise TranscriptionError("Poe 转写输出达到长度上限，已拒绝保存残缺文字稿")
        if finish_reason != "stop":
            raise TranscriptionError(f"Poe 转写异常结束: {finish_reason or 'missing'}")

        message = first.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise TranscriptionError("Poe 转写返回空文字")

        text = content.strip()
        return TranscriptResult(
            text=text,
            paragraphs=self._to_paragraphs(text),
            summary=None,
            chapters=None,
            keywords=None,
        )

    def _encode_audio(self, path: Path) -> str:
        size = path.stat().st_size
        if size <= 0:
            raise TranscriptionError("音频文件为空")
        if size > self.MAX_AUDIO_BYTES:
            raise TranscriptionError(
                f"音频文件超过 Poe 转写上限 ({self.MAX_AUDIO_BYTES / 1024 / 1024:.0f}MB)"
            )
        return base64.b64encode(path.read_bytes()).decode("ascii")

    @staticmethod
    def _to_paragraphs(text: str, max_chars: int = 600) -> list[str]:
        paragraphs: list[str] = []
        for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            sentences = re.findall(r".*?[。！？!?]+(?:[”’\"']+)?|.+$", line)
            current = ""
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                if current and len(current) + len(sentence) > max_chars:
                    paragraphs.append(current)
                    current = sentence
                else:
                    current += sentence
            if current:
                paragraphs.append(current)
        return paragraphs or [text.strip()]

    @staticmethod
    def _safe_suffix(url: str) -> str:
        suffix = Path(unquote(urlparse(url).path)).suffix.lower()
        if suffix in {".mp3", ".m4a", ".mp4", ".wav", ".aac", ".ogg", ".flac", ".webm"}:
            return suffix
        return ".mp3"

    @staticmethod
    def _resolve_mime_type(content_type: str, suffix: str) -> str:
        normalized = content_type.split(";", 1)[0].strip().lower()
        if normalized.startswith(("audio/", "video/")):
            return normalized
        guessed, _ = mimetypes.guess_type(f"audio{suffix}")
        return guessed or "audio/mpeg"

    @staticmethod
    def _content_length(response: httpx.Response) -> int | None:
        raw = response.headers.get("content-length", "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    @staticmethod
    async def _retry_delay(response: httpx.Response, attempt: int) -> None:
        raw = response.headers.get("retry-after", "").strip()
        try:
            delay = float(raw) if raw else float(2**attempt)
        except ValueError:
            delay = float(2**attempt)
        await asyncio.sleep(min(max(delay, 0.0), 30.0))

    @staticmethod
    def _http_error(response: httpx.Response) -> TranscriptionError:
        status = response.status_code
        if status == 401:
            return TranscriptionError("Poe API Key 无效或已过期")
        if status == 402:
            return TranscriptionError("Poe 积分不足")
        if status == 404:
            return TranscriptionError("Poe 转写模型不存在或暂不可用")
        if status == 413:
            return TranscriptionError("Poe 拒绝了过大的音频或上下文")
        if status == 429:
            return TranscriptionError("Poe 请求过于频繁，请稍后重试")
        return TranscriptionError(f"Poe 转写请求失败: HTTP {status}")
