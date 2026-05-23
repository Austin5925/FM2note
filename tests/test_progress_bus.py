"""Tests for the in-memory progress bus."""

from __future__ import annotations

import asyncio

import pytest

from src.web.progress import STAGES, ProgressBus, ProgressEvent, get_bus, reset_bus


class TestProgressBus:
    def test_create_returns_unique_task_ids(self):
        bus = ProgressBus()
        id1, q1 = bus.create()
        id2, q2 = bus.create()
        assert id1 != id2
        assert q1 is not q2
        assert isinstance(q1, asyncio.Queue)

    def test_get_queue_returns_none_for_unknown(self):
        bus = ProgressBus()
        assert bus.get_queue("nope") is None

    @pytest.mark.asyncio
    async def test_publish_pushes_event_to_queue(self):
        bus = ProgressBus()
        task_id, queue = bus.create()
        evt = ProgressEvent(stage="asr", status="start", message="hi")
        bus.publish(task_id, evt)
        received = await asyncio.wait_for(queue.get(), timeout=1)
        assert received is evt

    @pytest.mark.asyncio
    async def test_close_publishes_sentinel(self):
        bus = ProgressBus()
        bus._cleanup_delay = 0
        task_id, queue = bus.create()
        bus.close(task_id)
        item = await asyncio.wait_for(queue.get(), timeout=1)
        assert item is None
        # Give cleanup task one tick to run
        await asyncio.sleep(0.05)
        assert bus.get_queue(task_id) is None

    def test_publish_to_missing_task_silent(self):
        bus = ProgressBus()
        # Must not raise
        bus.publish("ghost", ProgressEvent(stage="resolve", status="start"))

    def test_update_record_round_trip(self):
        bus = ProgressBus()
        task_id, _ = bus.create()
        bus.update_record(task_id, note_path="/tmp/x.md", char_count=42)
        rec = bus.get_record(task_id)
        assert rec is not None
        assert rec.note_path == "/tmp/x.md"
        assert rec.char_count == 42

    def test_stages_constant_has_five_entries(self):
        assert len(STAGES) == 5
        assert STAGES == ("resolve", "subtitle_check", "asr", "summary", "write")

    def test_singleton_get_bus(self):
        reset_bus()
        b1 = get_bus()
        b2 = get_bus()
        assert b1 is b2
        reset_bus()


class TestProgressEvent:
    def test_to_dict_includes_all_fields(self):
        evt = ProgressEvent(stage="asr", status="done", message="ok", percent=100)
        d = evt.to_dict()
        assert d["stage"] == "asr"
        assert d["status"] == "done"
        assert d["message"] == "ok"
        assert d["percent"] == 100
        assert d["extra"] == {}
