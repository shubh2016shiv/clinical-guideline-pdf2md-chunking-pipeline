"""Async mutual exclusion for GPU engine access."""

from __future__ import annotations

import asyncio
import logging
import time
from types import TracebackType
from typing import Self

from ..contracts import GPUConfig, GPUNotAvailableError
from ..fault_tolerance import AsyncOperationTimeoutGuard

logger = logging.getLogger(__name__)

_GPU_LOCK = asyncio.Lock()


class ExclusiveGPUContextManager:
    """Acquire the process-wide async GPU lock for one engine operation."""

    def __init__(
        self,
        config: GPUConfig,
        timeout_guard: AsyncOperationTimeoutGuard,
        *,
        component_name: str,
    ) -> None:
        self._config = config
        self._timeout_guard = timeout_guard
        self._component_name = component_name
        self._acquired_at: float | None = None
        self._wait_started_at: float | None = None

    async def __aenter__(self) -> Self:
        if not self._config.enabled or self._config.force_cpu:
            raise GPUNotAvailableError(
                f"GPU access is disabled for component {self._component_name!r}.",
                context={
                    "component_name": self._component_name,
                    "gpu_enabled": self._config.enabled,
                    "force_cpu": self._config.force_cpu,
                    "cuda_device_id": self._config.cuda_device_id,
                },
            )

        # ---- pre-acquire: all fallible work happens here ----
        self._wait_started_at = time.monotonic()
        logger.info(
            "gpu.lock.waiting component=%s cuda_device_id=%s",
            self._component_name,
            self._config.cuda_device_id,
        )
        # ----------------------------------------------------

        async with self._timeout_guard.gpu_acquire():
            await _GPU_LOCK.acquire()

        # After acquire, the ONLY code is an infallible assignment
        # and return.  No logging, no I/O, no allocations that could
        # raise.  This guarantees __aexit__ is always reached, which
        # always releases the lock.
        self._acquired_at = time.monotonic()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        if self._acquired_at is None:
            return False

        _released_at = time.monotonic()
        held_seconds = _released_at - self._acquired_at
        wait_ms = (
            (self._acquired_at - self._wait_started_at) * 1000
            if self._wait_started_at is not None
            else None
        )

        # Reset state BEFORE releasing so a concurrent cancellation
        # cannot trigger a double-release.
        self._acquired_at = None
        self._wait_started_at = None
        _GPU_LOCK.release()

        logger.info(
            "gpu.lock.released component=%s cuda_device_id=%s held_seconds=%.3f wait_ms=%s",
            self._component_name,
            self._config.cuda_device_id,
            held_seconds,
            f"{wait_ms:.1f}" if wait_ms is not None else "?",
        )
        return False
