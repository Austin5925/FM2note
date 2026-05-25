"""GET /api/logs — incremental log fetch for the GUI log panel.

The frontend polls every few seconds with ``?after_seq=<last>`` and the
endpoint returns any newer records from the in-memory ring buffer.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.web.services.log_buffer import get_logs

router = APIRouter(prefix="/api")


@router.get("/logs")
async def list_logs(after_seq: int = 0, limit: int = 200) -> dict:
    """Return log records newer than ``after_seq`` (default: from the start).

    Response::

        {
          "records": [
            {"seq": 42, "time": "...", "level": "INFO", "module": "...",
             "line": 12, "message": "..."},
            ...
          ],
          "next_after_seq": 42  # pass back in the next poll
        }

    The buffer is capped at 10k records, so very-old seqs return the
    oldest available rows; the client should react to gaps by clearing
    its view and starting fresh.
    """
    records = get_logs(after_seq=after_seq, limit=limit)
    next_seq = records[-1]["seq"] if records else after_seq
    return {"records": records, "next_after_seq": next_seq}
