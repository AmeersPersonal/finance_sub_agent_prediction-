"""Batch copy of new PostgreSQL chunks into the Snowflake index.

Each batch is embedded and merged in Snowflake before it's marked synced in
PostgreSQL. A crash between the two re-sends that batch next time, and the
MERGE skips rows Snowflake already has, so re-runs never duplicate.
"""

from __future__ import annotations

from typing import Any

BATCH_SIZE = 200


def sync(repo: Any, index: Any, *, batch_size: int = BATCH_SIZE,
         max_batches: int | None = None) -> int:
    """Sync until nothing is pending (or `max_batches`); returns chunk/ticker rows synced."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    synced = batches = 0
    while max_batches is None or batches < max_batches:
        rows = repo.chunks_to_sync(index.embed_model, limit=batch_size)
        if not rows:
            break
        index.upsert(rows)
        repo.mark_chunks_synced(rows, index.embed_model)
        synced += len(rows)
        batches += 1
    return synced
