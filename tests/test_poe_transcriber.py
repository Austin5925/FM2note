"""Tests for Poe Qwen3.5 Omni audio transcription.

The response fixture was captured from a live ``qwen3.5-omni-flash`` Poe
Chat Completions request on 2026-07-12, then checked for credentials before
being committed. Tests never call the real API.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.models import TranscriptResult
from src.transcriber.base import TranscriptionError
from src.transcriber.poe import (
    DEFAULT_POE_ASR_MODEL,
    POE_ASR_MODELS,
    PoeTranscriber,
)

FIXTURE = Path(__file__).parent / "fixtures" / "poe_qwen_asr_response.json"


def _real_response() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_default_and_selectable_models(tmp_path):
    default = PoeTranscriber("pk-test", temp_dir=str(tmp_path))
    plus = PoeTranscriber("pk-test", model="qwen3.5-omni-plus", temp_dir=str(tmp_path))

    assert DEFAULT_POE_ASR_MODEL == "qwen3.5-omni-flash"
    assert POE_ASR_MODELS == ("qwen3.5-omni-flash", "qwen3.5-omni-plus")
    assert default.name == "poe/qwen3.5-omni-flash"
    assert plus.name == "poe/qwen3.5-omni-plus"


def test_unknown_model_is_rejected(tmp_path):
    with pytest.raises(TranscriptionError, match="不支持的 Poe 转写模型"):
        PoeTranscriber("pk-test", model="arbitrary-bot", temp_dir=str(tmp_path))


def test_build_payload_uses_file_attachment_not_native_audio_field(tmp_path):
    transcriber = PoeTranscriber("pk-test", temp_dir=str(tmp_path))
    payload = transcriber._build_payload("episode.m4a", "audio/mp4", "YWJj", "cn")

    assert payload["model"] == "qwen3.5-omni-flash"
    assert payload["stream"] is False
    assert payload["output_mode"] == "text"
    assert "audio" not in payload
    content = payload["messages"][0]["content"]
    assert content[1] == {
        "type": "file",
        "file": {
            "filename": "episode.m4a",
            "file_data": "data:audio/mp4;base64,YWJj",
        },
    }
    assert "不要翻译" in content[0]["text"]


def test_parse_captured_live_response(tmp_path):
    transcriber = PoeTranscriber("pk-test", temp_dir=str(tmp_path))
    result = transcriber._parse_response(_real_response())

    assert result.text == "欢迎大家来体验达摩院推出的语音识别模型。"
    assert result.paragraphs == [result.text]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({}, "缺少 choices"),
        ({"choices": []}, "缺少 choices"),
        (
            {"choices": [{"finish_reason": "length", "message": {"content": "半截"}}]},
            "拒绝保存残缺文字稿",
        ),
        (
            {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]},
            "返回空文字",
        ),
        (
            {"choices": [{"finish_reason": "content_filter", "message": {"content": "x"}}]},
            "异常结束",
        ),
    ],
)
def test_invalid_or_truncated_responses_are_rejected(tmp_path, body, message):
    transcriber = PoeTranscriber("pk-test", temp_dir=str(tmp_path))
    with pytest.raises(TranscriptionError, match=message):
        transcriber._parse_response(body)


def test_flat_text_is_split_into_readable_paragraphs(tmp_path):
    transcriber = PoeTranscriber("pk-test", temp_dir=str(tmp_path))
    text = "第一句。第二句。第三句。"
    assert transcriber._to_paragraphs(text, max_chars=8) == ["第一句。第二句。", "第三句。"]


@pytest.mark.asyncio
async def test_transcribe_cleans_download_after_success(tmp_path):
    transcriber = PoeTranscriber("pk-test", temp_dir=str(tmp_path))
    downloaded = tmp_path / "downloaded.mp3"
    downloaded.write_bytes(b"audio")
    expected = TranscriptResult(text="正文", paragraphs=["正文"])
    transcriber._download_audio = AsyncMock(return_value=(downloaded, "audio/mpeg"))
    transcriber._transcribe_file = AsyncMock(return_value=expected)

    result = await transcriber.transcribe("https://example.com/episode.mp3")

    assert result is expected
    assert not downloaded.exists()


@pytest.mark.asyncio
async def test_transcribe_cleans_download_after_api_failure(tmp_path):
    transcriber = PoeTranscriber("pk-test", temp_dir=str(tmp_path))
    downloaded = tmp_path / "downloaded.mp3"
    downloaded.write_bytes(b"audio")
    transcriber._download_audio = AsyncMock(return_value=(downloaded, "audio/mpeg"))
    transcriber._transcribe_file = AsyncMock(side_effect=TranscriptionError("upstream"))

    with pytest.raises(TranscriptionError, match="upstream"):
        await transcriber.transcribe("https://example.com/episode.mp3")

    assert not downloaded.exists()


@pytest.mark.asyncio
async def test_transcribe_file_sends_and_parses_wire_shape(tmp_path):
    transcriber = PoeTranscriber("pk-test", temp_dir=str(tmp_path))
    audio = tmp_path / "episode.wav"
    audio.write_bytes(b"RIFF-test")
    response = httpx.Response(200, json=_real_response())

    client = AsyncMock()
    client.post.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client
    context.__aexit__.return_value = False

    with patch("src.transcriber.poe.httpx.AsyncClient", return_value=context):
        result = await transcriber._transcribe_file(audio, "audio/wav", "cn")

    assert result.text.startswith("欢迎大家")
    request = client.post.call_args
    assert request.args[0].endswith("/chat/completions")
    assert request.kwargs["json"]["messages"][0]["content"][1]["type"] == "file"


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "API Key"),
        (402, "积分不足"),
        (404, "模型不存在"),
        (413, "过大的音频"),
        (429, "请求过于频繁"),
        (500, "HTTP 500"),
    ],
)
def test_http_errors_are_user_friendly(status, message):
    error = PoeTranscriber._http_error(httpx.Response(status))
    assert message in str(error)
