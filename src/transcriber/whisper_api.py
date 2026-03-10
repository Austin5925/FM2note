from __future__ import annotations

from pathlib import Path

import httpx
from loguru import logger

from src.models import TranscriptResult
from src.transcriber.base import TranscriptionError


class WhisperTranscriber:
    """OpenAI Whisper API 转写实现

    单次文件限制 25MB，需分片处理
    """

    MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB

    def __init__(self, api_key: str, temp_dir: str = "./data/tmp"):
        self._api_key = api_key
        self._temp_dir = Path(temp_dir)
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return "whisper_api"

    async def transcribe(
        self,
        audio_url: str,
        language: str = "cn",
    ) -> TranscriptResult:
        """下载音频并调用 Whisper API 转写。

        Args:
            audio_url: 音频文件 URL
            language: 语言代码（Whisper 使用 ISO-639-1，中文为 'zh'）

        Returns:
            TranscriptResult（不含摘要和章节）

        Raises:
            TranscriptionError: 转写失败
        """
        whisper_lang = "zh" if language == "cn" else language

        # 下载音频
        audio_path = await self._download_audio(audio_url)
        try:
            file_size = audio_path.stat().st_size

            if file_size > self.MAX_FILE_SIZE:
                # 分片处理
                text = await self._transcribe_chunked(audio_path, whisper_lang)
            else:
                text = await self._transcribe_single(audio_path, whisper_lang)

            paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
            if not paragraphs:
                paragraphs = [text]

            return TranscriptResult(
                text=text,
                paragraphs=paragraphs,
                summary=None,
                chapters=None,
                keywords=None,
            )
        finally:
            if audio_path.exists():
                audio_path.unlink()

    async def _download_audio(self, url: str) -> Path:
        """下载音频到临时文件"""
        filename = url.split("/")[-1].split("?")[0] or "audio.mp3"
        filepath = self._temp_dir / filename

        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
            try:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with open(filepath, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                            f.write(chunk)
            except httpx.HTTPError as e:
                raise TranscriptionError(f"下载音频失败: {e}") from e

        logger.info("音频下载完成: {} ({:.1f}MB)", filepath.name, filepath.stat().st_size / 1e6)
        return filepath

    async def _transcribe_single(self, audio_path: Path, language: str) -> str:
        """单文件转写"""
        from openai import OpenAI

        client = OpenAI(api_key=self._api_key)

        try:
            with open(audio_path, "rb") as f:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    language=language,
                    response_format="text",
                )
            return response
        except Exception as e:
            raise TranscriptionError(f"Whisper API 转写失败: {e}") from e

    async def _transcribe_chunked(self, audio_path: Path, language: str) -> str:
        """分片转写大文件"""
        from pydub import AudioSegment

        logger.info("文件超过 25MB，开始分片处理")

        audio = AudioSegment.from_file(str(audio_path))
        chunk_duration_ms = 10 * 60 * 1000  # 10 分钟一片
        chunks = []

        for i in range(0, len(audio), chunk_duration_ms):
            chunk = audio[i : i + chunk_duration_ms]
            chunk_path = self._temp_dir / f"chunk_{i // chunk_duration_ms}.mp3"
            chunk.export(str(chunk_path), format="mp3")
            chunks.append(chunk_path)

        logger.info("分片完成: {} 片", len(chunks))

        texts = []
        for chunk_path in chunks:
            text = await self._transcribe_single(chunk_path, language)
            texts.append(text)
            chunk_path.unlink()

        return "\n".join(texts)
