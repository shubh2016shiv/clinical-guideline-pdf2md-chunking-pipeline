"""
stage2_page_extraction/windowed_extraction/gpu_engine_resource_coordinator.py
============================================================================
Stage 2 · coordinate exclusive GPU ownership for a conversion engine.

Docling and MinerU can both keep model memory resident between windows. The resource
boundary is therefore the engine lifecycle, not a single page window: the engine must
own the GPU before it starts, while it converts every remaining window, and until it
has stopped and released its models.

In CPU-only mode (no GPU, or GPU explicitly disabled) this coordinator becomes a
no-op. The engines still run; there is simply no process-wide GPU lock to acquire.

On VRAM: the coordinator records current GPU memory before engine startup and before
each window. It does not hard-abort on a high reading. The exclusive lease prevents
another local engine from competing, and engine failures remain the responsibility of
the fault-tolerance layer.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from ...contracts.configurations.pipeline_config import GPUConfig
from ...fault_tolerance import AsyncOperationTimeoutGuard
from ...gpu_resource_management import ExclusiveGPUContextManager, GPUVRAMUsageMonitor

logger = logging.getLogger(__name__)


class GpuEngineResourceCoordinator:
    """
    Lease the exclusive GPU context for one engine lifecycle.

    Constructed once per run and used as an async context manager around the
    engine's ``start`` → window conversion loop → ``stop`` lifecycle::

        async with coordinator.engine_lifecycle():
            async with engine:
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
    async def engine_lifecycle(self) -> AsyncGenerator[None, None]:
        """
        Hold the exclusive GPU lease while the engine is alive.

        In CPU mode this is a no-op pass-through. In GPU mode it logs current VRAM,
        acquires the process-wide GPU lock (bounded by the ``gpu_acquire`` timeout),
        and holds it until the engine has stopped.
        """
        if not self._gpu_config.enabled or self._gpu_config.force_cpu:
            yield
            return

        self._log_vram("engine_start", window_index=None)
        async with ExclusiveGPUContextManager(
            self._gpu_config,
            self._timeout_guard,
            component_name=self._component_name,
        ):
            yield

    def observe_window_start(self, window_index: int) -> None:
        """Record current GPU memory before a window starts."""
        if not self._gpu_config.enabled or self._gpu_config.force_cpu:
            return
        self._log_vram("window_start", window_index=window_index)

    def _log_vram(self, event: str, *, window_index: int | None) -> None:
        """Record current GPU memory use for leak and window-size observability."""
        used_mb = self._vram_monitor.current_used_mb()
        logger.info(
            "gpu.vram_before event=%s component=%s window_index=%s used_vram_mb=%s budget_mb=%s",
            event,
            self._component_name,
            window_index,
            used_mb,
            self._gpu_config.max_vram_mb,
        )
