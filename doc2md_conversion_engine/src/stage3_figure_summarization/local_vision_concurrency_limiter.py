"""
stage3_figure_summarization/local_vision_concurrency_limiter.py
================================================================
In-flight concurrency cap for the local Ollama VLM.

Why this (and not a request-per-minute limiter)?
------------------------------------------------
A *cloud* vision API is throttled by RPM ceilings: the right primitive is a
token-bucket rate limiter.  The local Ollama topology is the opposite — the
single GPU is the bottleneck and Ollama serializes vision+thinking requests
internally.  Oversubscribing only thrashes VRAM and slows everything down.
The right primitive is an **in-flight semaphore**: at most N requests may be
*in progress* at the same time, regardless of how fast they each finish.

This module is a thin domain wrapper over ``asyncio.Semaphore`` so:

* the orchestrator depends on a named pipeline concept, not on the stdlib
  type;
* swapping in an alternate limiter (e.g. one that also peeks VRAM through
  :class:`GPUVRAMUsageMonitor` before granting) is a one-line change.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class LocalVisionConcurrencyLimiter:
    """
    Asynchronous concurrency limiter for local-model in-flight requests.

    Usage::

        async with limiter.acquire():
            await vision_client.summarize(...)

    The ``acquire`` context manager guarantees the slot is released even
    when the wrapped call raises.
    """

    def __init__(self, *, in_flight_limit: int) -> None:
        if in_flight_limit < 1:
            raise ValueError("in_flight_limit must be ≥ 1")
        self._semaphore = asyncio.Semaphore(in_flight_limit)
        self._in_flight_limit = in_flight_limit
        self._currently_in_flight = 0

    @property
    def in_flight_limit(self) -> int:
        return self._in_flight_limit

    @property
    def currently_in_flight(self) -> int:
        # Informational; useful for metrics and operator dashboards.  Not
        # safe to use for routing decisions because it races the semaphore.
        return self._currently_in_flight

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        await self._semaphore.acquire()
        self._currently_in_flight += 1
        try:
            yield
        finally:
            self._currently_in_flight -= 1
            self._semaphore.release()
