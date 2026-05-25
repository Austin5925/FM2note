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

    @pytest.mark.asyncio
    async def test_mark_backfill_skipped_inserts_new_rows(self, state):
        """v1.4.15 — bulk-mark feed entries as ``backfill_skipped`` so future
        polls treat them as processed and skip ASR entirely."""
        items = [
            ("g_skip_1", "Pod A", "Episode 1"),
            ("g_skip_2", "Pod A", "Episode 2"),
            ("g_skip_3", "Pod A", "Episode 3"),
        ]
        inserted = await state.mark_backfill_skipped(items)
        assert inserted == 3
        for guid, _, _ in items:
            assert await state.is_processed(guid) is True

    @pytest.mark.asyncio
    async def test_mark_backfill_skipped_does_not_clobber_done(self, state):
        """Existing rows (especially ``done``) must NOT be overwritten by a
        retroactive backfill mark — that would lose the note_path and history."""
        await state.mark_status("g1", "done", podcast_name="P", title="T", note_path="/x.md")
        inserted = await state.mark_backfill_skipped([("g1", "P", "T"), ("g2", "P", "T2")])
        # Only g2 was new; g1 stays "done"
        assert inserted == 1
        records = {r.guid: r for r in await state.get_all()}
        assert records["g1"].status == "done"
        assert records["g1"].note_path == "/x.md"
        assert records["g2"].status == "backfill_skipped"

    @pytest.mark.asyncio
    async def test_mark_backfill_skipped_empty_is_noop(self, state):
        assert await state.mark_backfill_skipped([]) == 0


class TestGetRecentHistory:
    """v1.5.2 audit fix (Code Review A3): bounded query for the history page,
    filters out backfill_skipped rows by default, lets the DB do the sort."""

    @pytest.mark.asyncio
    async def test_limit_caps_results(self, state):
        for i in range(20):
            await state.mark_status(f"g{i}", "done", podcast_name="P", title=f"T{i}")
        rows = await state.get_recent_history(limit=5)
        assert len(rows) == 5

    @pytest.mark.asyncio
    async def test_orders_by_updated_at_desc(self, state):
        await state.mark_status("first", "done", podcast_name="P", title="first ep")
        await state.mark_status("second", "done", podcast_name="P", title="second ep")
        await state.mark_status("third", "done", podcast_name="P", title="third ep")
        rows = await state.get_recent_history(limit=10)
        titles = [r.title for r in rows]
        # Newest first
        assert titles[0] == "third ep"
        assert titles[-1] == "first ep"

    @pytest.mark.asyncio
    async def test_excludes_backfill_skipped_by_default(self, state):
        await state.mark_status("done1", "done", podcast_name="P", title="real")
        await state.mark_backfill_skipped([("skip1", "P", "skipped")])
        rows = await state.get_recent_history(limit=10)
        assert [r.guid for r in rows] == ["done1"]

    @pytest.mark.asyncio
    async def test_include_backfill_skipped_when_requested(self, state):
        await state.mark_status("done1", "done", podcast_name="P", title="real")
        await state.mark_backfill_skipped([("skip1", "P", "skipped")])
        rows = await state.get_recent_history(limit=10, include_backfill_skipped=True)
        guids = {r.guid for r in rows}
        assert guids == {"done1", "skip1"}

    @pytest.mark.asyncio
    async def test_filter_and_limit_interact_correctly(self, state):
        """v1.5.2 Code Review #3 coverage gap: when both done rows AND
        backfill_skipped rows exist, the LIMIT must apply *after* the
        WHERE filter — otherwise the response would include skip rows or
        return fewer than expected. Set up the worst case: 5 done + many
        backfill_skipped, ask for limit=5, must get exactly the 5 done."""
        for i in range(5):
            await state.mark_status(f"done_{i}", "done", podcast_name="P", title=f"real {i}")
        await state.mark_backfill_skipped([(f"skip_{j}", "P", f"hidden {j}") for j in range(100)])
        rows = await state.get_recent_history(limit=5)
        assert len(rows) == 5
        # Every returned row must be done (no leaked skip rows)
        assert all(r.status == "done" for r in rows)
        assert all(r.guid.startswith("done_") for r in rows)


class TestMarkStatusTransaction:
    """v1.5.2 Codex audit fix: mark_status now wraps SELECT+UPDATE in an
    explicit transaction to prevent lost retry-count increments under
    concurrent connections."""

    @pytest.mark.asyncio
    async def test_failed_increment_round_trip(self, state):
        # Two sequential failures must produce retry_count=2 deterministically
        await state.mark_status("g1", "pending", podcast_name="P", title="T")
        await state.mark_status("g1", "failed", error_msg="e1")
        await state.mark_status("g1", "failed", error_msg="e2")
        rows = await state.get_recent_history(limit=5)
        assert rows[0].retry_count == 2
