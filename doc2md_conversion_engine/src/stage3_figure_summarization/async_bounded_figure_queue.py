"""
stage3_figure_summarization/async_bounded_figure_queue.py
==========================================================
Bounded async queue between Stage 2's figure stream and Stage 3's worker pool.

Why bounded?
------------
Stage 2 (extraction) typically runs faster than Stage 3 (local VLM with
thinking).  Without an upper bound on the in-flight queue, extraction would
buffer figures unboundedly in RAM until summarization caught up — exactly
the failure mode that kills long batch jobs.  A bounded queue applies
**backpressure**: when full, the producer's ``put`` *waits* until a worker
dequeues, so memory stays flat.

Why a thin wrapper around ``asyncio.Queue``?
--------------------------------------------
``asyncio.Queue`` already gives us bounded capacity + async ``put``/``get``.
The wrapper adds two pipeline-specific concerns the stdlib does not:

1. A **producer-closed** signal — workers need a clean way to know "no more
   figures will ever arrive" so they exit instead of hanging on ``get``
   forever.  This is implemented by enqueueing a sentinel ``None`` per
   worker on ``close()``; ``get()`` returns ``None`` to its caller as the
   exit signal.
2. Conformance to :class:`AbstractFigureWorkQueue` — so the orchestrator
   depends on the contract, not on the stdlib type.
"""

from __future__ import annotations

import asyncio
import logging

from ..contracts import AbstractFigureWorkQueue, Figure

logger = logging.getLogger(__name__)


class AsyncBoundedFigureQueue(AbstractFigureWorkQueue):
    """
    Bounded queue of :class:`Figure` items with a clean shutdown signal.

    Workers call :meth:`get` in a loop and treat a ``None`` return as
    "producer closed; exit".  The orchestrator must call :meth:`close`
    once Stage 2 has finished producing — it enqueues exactly ``num_workers``
    sentinels so every worker wakes up and terminates.
    """

    def __init__(self, *, max_queue_size: int, num_workers: int) -> None:
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be ≥ 1")
        if num_workers < 1:
            raise ValueError("num_workers must be ≥ 1")
        self._queue: asyncio.Queue[Figure | None] = asyncio.Queue(maxsize=max_queue_size)
        self._num_workers = num_workers
        self._closed = False
        self._close_guard = asyncio.Lock()

    async def put(self, figure: Figure) -> None:
        if self._closed:
            # Defensive: callers must not enqueue after close.  Raising here
            # surfaces orchestration bugs immediately rather than silently
            # dropping figures.
            raise RuntimeError(
                "AsyncBoundedFigureQueue.put called after close — extraction "
                "produced a figure after Stage 2's producer signalled done."
            )
        await self._queue.put(figure)

    async def get(self) -> Figure | None:
        item = await self._queue.get()
        # ``None`` is the per-worker shutdown sentinel — never a real Figure.
        return item

    async def close(self) -> None:
        async with self._close_guard:
            if self._closed:
                return
            self._closed = True
            # Enqueue one sentinel per worker so every worker wakes up.
            # Using ``put`` (not ``put_nowait``) means we still respect
            # backpressure if the queue is full at shutdown.
            for _ in range(self._num_workers):
                await self._queue.put(None)
        logger.debug(
            "stage3.queue.closed sentinels_enqueued=%d", self._num_workers
        )

    def qsize(self) -> int:
        return self._queue.qsize()
