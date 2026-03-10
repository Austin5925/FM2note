from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.downloader.audio import AudioDownloader


@pytest.fixture
def downloader(tmp_path):
    return AudioDownloader(str(tmp_path))


class TestAudioDownloader:
    @pytest.mark.asyncio
    async def test_download_creates_file(self, downloader, tmp_path):
        # Mock httpx streaming response
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        async def aiter_bytes(chunk_size=None):
            yield b"fake audio data " * 100

        mock_resp.aiter_bytes = aiter_bytes
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        import httpx

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx, "AsyncClient", lambda **kw: mock_client)
            path = await downloader.download("https://example.com/test.mp3", "test.mp3")

        assert path.exists()
        assert path.name == "test.mp3"

    @pytest.mark.asyncio
    async def test_cleanup_removes_file(self, downloader, tmp_path):
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"data")
        assert test_file.exists()

        await downloader.cleanup(test_file)
        assert not test_file.exists()

    @pytest.mark.asyncio
    async def test_cleanup_nonexistent_file(self, downloader, tmp_path):
        # 不应报错
        await downloader.cleanup(tmp_path / "nonexistent.mp3")
