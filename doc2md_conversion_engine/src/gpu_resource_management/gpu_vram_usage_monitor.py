"""Read-only GPU VRAM usage checks."""

from __future__ import annotations

import importlib
import logging
from types import ModuleType
from typing import Any, cast

from ..contracts import GPUConfig, GPUError, GPUNotAvailableError

logger = logging.getLogger(__name__)

_BYTES_PER_MIB = 1024 * 1024


class GPUVRAMUsageMonitor:
    """Queries current NVIDIA VRAM usage without allocating GPU memory."""

    def __init__(self, config: GPUConfig) -> None:
        self._config = config

    def current_used_mb(self) -> int:
        """Return current used VRAM in MiB, or 0 when NVML/GPU is unavailable."""
        return self._read_memory_field("used", default=0)

    def current_free_mb(self) -> int:
        """
        Return currently free VRAM in MiB, or 0 when NVML/GPU is unavailable.

        Used for proactive backend selection: a capability rung is reachable only when
        the free VRAM (capped by the configured budget) clears the rung's requirement.
        Returns 0 in CPU mode or when NVML cannot be read, so GPU rungs are skipped and
        the engine starts at a CPU-capable rung — the safe default.
        """
        return self._read_memory_field("free", default=0)

    def _read_memory_field(self, field: str, *, default: int) -> int:
        """Read one NVML device-memory field (``used``/``free``/``total``) in MiB."""
        if not self._config.enabled or self._config.force_cpu:
            return default

        pynvml = self._load_pynvml()
        if pynvml is None:
            return default

        try:
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(self._config.cuda_device_id)
            memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            return int(getattr(memory_info, field) // _BYTES_PER_MIB)
        except Exception as exc:
            logger.warning(
                "gpu.vram.unavailable cuda_device_id=%s field=%s reason=%s",
                self._config.cuda_device_id,
                field,
                type(exc).__name__,
            )
            return default
        finally:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                logger.debug("gpu.vram.nvml_shutdown_failed", exc_info=True)

    def assert_within_budget(self, max_mb: int | None = None) -> None:
        """Raise when GPU mode is disabled or current VRAM exceeds the budget."""
        if not self._config.enabled or self._config.force_cpu:
            raise GPUNotAvailableError(
                "GPU VRAM budget check requested while GPU access is disabled.",
                context={
                    "gpu_enabled": self._config.enabled,
                    "force_cpu": self._config.force_cpu,
                    "cuda_device_id": self._config.cuda_device_id,
                },
            )

        budget_mb = max_mb if max_mb is not None else self._config.max_vram_mb
        used_mb = self.current_used_mb()
        if used_mb > budget_mb:
            raise GPUError(
                f"GPU VRAM usage {used_mb} MiB exceeds budget {budget_mb} MiB.",
                context={
                    "cuda_device_id": self._config.cuda_device_id,
                    "used_vram_mb": used_mb,
                    "max_vram_mb": budget_mb,
                },
            )

    def _load_pynvml(self) -> Any | None:
        try:
            return cast(ModuleType, importlib.import_module("pynvml"))
        except ImportError:
            logger.warning("gpu.vram.pynvml_unavailable")
            return None
