"""Module-level asyncio locks guarding read-modify-write of .env and YAML.

Two browser tabs hitting ``PUT /api/settings`` (or two subscription edits)
without coordination would last-writer-wins, silently dropping disjoint
changes. These locks serialize the full read-merge-replace cycle.
"""

from __future__ import annotations

import asyncio

env_lock: asyncio.Lock = asyncio.Lock()
yaml_lock: asyncio.Lock = asyncio.Lock()
