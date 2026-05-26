"""
stage2_page_extraction/windowed_extraction/gpu_window_scheduler.py
==================================================================
Stage 2 · make sure only one engine uses the GPU at a time, one window at a time.

Docling and MinerU both want the GPU, and the GPU has one pool of memory. If two
engines tried to use it at once they would fight for VRAM and likely crash. This
scheduler is the gatekeeper: before a window is converted it takes an exclusive lease
on the GPU, and it releases the lease when the window is done.

It also adapts to the machine. In CPU-only mode (no GPU, or GPU explicitly disabled)
there is nothing to lease, so the scheduler simply steps aside and lets the window run
— Docling and MinerU's CPU pipeline work fine without a lock.

On VRAM: the scheduler *observes* GPU memory before each window and logs it, which is
the useful signal for spotting a leak or a too-large window. It does not hard-abort on
a high reading: the exclusive lease already guarantees no other engine is competing,
and failing a window because of memory another component is about to release would be
fragile. Aborting is left to the engine's own timeout/error handling.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from ...contracts.configurations.pipeline_config import GPUConfig
from ...fault_tolerance import AsyncOperationTimeoutGuard
from ...gpu_resource_management import ExclusiveGPUContextManager, GPUVRAMUsageMonitor

logger = logging.getLogger(__name__)


class GpuWindowScheduler:
    """
    Lease the exclusive GPU context for one extraction window.

    Constructed once per run and used as an async context manager around each
    window's conversion::

        async with scheduler.lease_for_window(window.index):
            async for page in engine.convert_window(...):
                ...
    """

    def __init__(
        self,
        gpu_config: GPUConfig,
        vram_monitor: GPUVRAMUsageMonitor,
        timeout_guard: AsyncOperationTimeoutGuard,
        *,
        component_name: str,
    ) -> None:
        self._gpu_config = gpu_config
        self._vram_monitor = vram_monitor
        self._timeout_guard = timeout_guard
        self._component_name = component_name

    @asynccontextmanager
    async def lease_for_window(self, window_index: int) -> AsyncGenerator[None, None]:
        """
        Hold the exclusive GPU lease for the duration of one window.

        In CPU mode this is a no-op pass-through. In GPU mode it logs current VRAM
        for observability, then acquires the process-wide GPU lock (bounded by the
        ``gpu_acquire`` timeout) and holds it until the window completes.
        """
        if not self._gpu_config.enabled or self._gpu_config.force_cpu:
            # CPU mode: no GPU to lease, nothing to serialise.
            yield
            return

        self._log_vram_before_window(window_index)
        async with ExclusiveGPUContextManager(
            self._gpu_config,
            self._timeout_guard,
            component_name=self._component_name,
        ):
            yield

    def _log_vram_before_window(self, window_index: int) -> None:
        """Record current GPU memory use before a window, for leak/size observability."""
        used_mb = self._vram_monitor.current_used_mb()
        logger.info(
            "gpu.window.vram_before component=%s window_index=%s used_vram_mb=%s budget_mb=%s",
            self._component_name,
            window_index,
            used_mb,
            self._gpu_config.max_vram_mb,
        )
