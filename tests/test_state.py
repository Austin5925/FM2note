from __future__ import annotations

import pytest

from src.monitor.state import StateManager


@pytest.fixture
async def state(tmp_path):
    db_path = str(tmp_path / "test_state.db")
    sm = StateManager(db_path)
    await sm.init()
    yield sm
    await sm.close()


class TestStateManager:
    @pytest.mark.asyncio
    async def test_is_processed_false_when_empty(self, state):
        assert await state.is_processed("nonexistent") is False

    @pytest.mark.asyncio
    async def test_mark_done_then_is_processed(self, state):
        await state.mark_status("g1", "done", podcast_name="p1", title="t1")
        assert await state.is_processed("g1") is True

    @pytest.mark.asyncio
    async def test_pending_not_counted_as_processed(self, state):
        await state.mark_status("g1", "pending", podcast_name="p1", title="t1")
        assert await state.is_processed("g1") is False

    @pytest.mark.asyncio
    async def test_status_transitions(self, state):
        await state.mark_status("g1", "pending", podcast_name="p1", title="t1")
        await state.mark_status("g1", "transcribing")
        await state.mark_status("g1", "writing")
        await state.mark_status("g1", "done", note_path="/vault/note.md")

        assert await state.is_processed("g1") is True

        all_records = await state.get_all()
        assert len(all_records) == 1
        assert all_records[0].status == "done"
        assert all_records[0].note_path == "/vault/note.md"

    @pytest.mark.asyncio
    async def test_mark_failed_increments_retry(self, state):
        await state.mark_status("g1", "pending", podcast_name="p1", title="t1")
        await state.mark_status("g1", "failed", error_msg="超时")
        await state.mark_status("g1", "failed", error_msg="再次超时")

        all_records = await state.get_all()
        assert all_records[0].retry_count == 2
        assert all_records[0].error_msg == "再次超时"

    @pytest.mark.asyncio
    async def test_get_failed_respects_max_retries(self, state):
        # 重试次数 < max_retries → 应返回
        await state.mark_status("g1", "pending", podcast_name="p1", title="可重试")
        await state.mark_status("g1", "failed", error_msg="err")

        failed = await state.get_failed(max_retries=3)
        assert len(failed) == 1
        assert failed[0].guid == "g1"

        # 重试 3 次后不再返回
        await state.mark_status("g1", "failed", error_msg="err")
        await state.mark_status("g1", "failed", error_msg="err")

        failed = await state.get_failed(max_retries=3)
        assert len(failed) == 0

    @pytest.mark.asyncio
    async def test_get_failed_excludes_done(self, state):
        await state.mark_status("g1", "done", podcast_name="p1", title="t1")
        failed = await state.get_failed()
        assert len(failed) == 0

    @pytest.mark.asyncio
    async def test_failed_within_retries_not_processed(self, state):
        """失败次数未超上限的任务不算 processed（允许重试）"""
        await state.mark_status("g1", "pending", podcast_name="p1", title="t1")
        await state.mark_status("g1", "failed", error_msg="err")
        assert await state.is_processed("g1") is False  # retry_count=1 < 3

    @pytest.mark.asyncio
    async def test_failed_exceeding_retries_is_processed(self, state):
        """失败次数超过上限的任务算 processed（不再重试）"""
        await state.mark_status("g1", "pending", podcast_name="p1", title="t1")
        await state.mark_status("g1", "failed", error_msg="err")
        await state.mark_status("g1", "failed", error_msg="err")
        await state.mark_status("g1", "failed", error_msg="err")
        # retry_count=3 >= max_retries=3
        assert await state.is_processed("g1") is True

    @pytest.mark.asyncio
    async def test_get_all(self, state):
        await state.mark_status("g1", "done", podcast_name="p1", title="t1")
        await state.mark_status("g2", "failed", podcast_name="p2", title="t2", error_msg="err")

        all_records = await state.get_all()
        assert len(all_records) == 2
