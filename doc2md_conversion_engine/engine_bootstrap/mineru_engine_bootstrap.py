"""
engine_bootstrap/mineru_engine_bootstrap.py
============================================
Prepare MinerU to run: confirm its tools are installed and download its models.

MinerU is the painful case that motivates this whole layer. Its ``mineru-api`` server,
when asked to preload a VLM, downloads several gigabytes of model weights — and if that
download happens inside the server's startup window, a health-check timeout fires on a
server that is doing exactly the right thing, just slowly. So we move the download here,
out of any timeout.

What this bootstrap does
------------------------
1. Confirms the MinerU command-line tools are installed (``mineru-api`` to serve, and
   ``mineru-models-download`` to fetch weights). If they are missing, it fails with a
   clear "install MinerU" message rather than a confusing timeout later.
2. Works out which ladder rungs are actually **reachable** on this machine (the same
   resolver the engine uses), then downloads the model families those rungs need —
   the VLM family only when a GPU big enough to run it is present, the pipeline family
   for the CPU-capable floor. No wasted multi-GB VLM download on a card that can't run
   the VLM, and every rung the engine might step to has its weights ready.
3. Downloads each family via ``mineru-models-download`` (untimed; a no-op once cached).

After this returns, starting ``mineru-api`` only has to *load* cached weights, which is
bounded — so the engine's startup timeout becomes meaningful again.
"""

from __future__ import annotations

import logging
import os
import shutil

from ..contracts.configurations.mineru_engine_config import MinerUEngineConfig
from ..contracts.configurations.pipeline_config import GPUConfig
from ..contracts.pipeline_domain_types import ExtractionEngine
from ..gpu_resource_management import GPUVRAMUsageMonitor
from .engine_bootstrap_interface import (
    AbstractEngineBootstrap,
    EngineBootstrapError,
    EngineReadinessReport,
)
from .mineru_backend_ladder import (
    configured_ladder,
    model_families_for_rungs,
    resolve_reachable_rungs,
)
from .model_provisioning_runner import run_provisioning_command

logger = logging.getLogger(__name__)

# Where weights are fetched from. MinerU honours MINERU_MODEL_SOURCE; we mirror it so a
# deployment can point at an internal mirror, defaulting to the public HuggingFace repo.
_DEFAULT_MODEL_SOURCE = "huggingface"
_MODEL_SOURCE_ENV_VAR = "MINERU_MODEL_SOURCE"

# The tools MinerU must provide for the engine to run at all.
_REQUIRED_EXECUTABLES = ("mineru-api", "mineru-models-download")


class MinerUEngineBootstrap(AbstractEngineBootstrap):
    """
    Ensure MinerU's tools and the reachable rungs' model weights are present.

    Constructed from the same configuration the engine uses, and resolves the same
    reachable ladder the engine will, so it downloads exactly the weights the engine
    might load — never the wrong family, never a family for an unreachable rung::

        bootstrap = MinerUEngineBootstrap(config.mineru_engine, config.gpu)
        report = await bootstrap.ensure_ready()
    """

    def __init__(self, config: MinerUEngineConfig, gpu_config: GPUConfig) -> None:
        self._config = config
        self._gpu_config = gpu_config
        self._vram_monitor = GPUVRAMUsageMonitor(gpu_config)

    @property
    def engine_type(self) -> ExtractionEngine:
        return ExtractionEngine.MINERU

    async def ensure_ready(self) -> EngineReadinessReport:
        """Confirm MinerU's tools exist and download every reachable rung's models."""
        self._require_executables()

        reachable = resolve_reachable_rungs(
            configured_ladder(self._config),
            free_vram_mb=self._vram_monitor.current_free_mb(),
            max_vram_mb=self._gpu_config.max_vram_mb,
            server_url=self._config.server_url,
        )
        families = model_families_for_rungs(reachable)
        model_source = self._model_source()
        for family in families:
            await run_provisioning_command(
                ["mineru-models-download", "--source", model_source, "--model_type", family],
                description=f"MinerU {family} model download (source={model_source})",
            )

        starting_backend = reachable[0].backend if reachable else None
        return EngineReadinessReport(
            engine=ExtractionEngine.MINERU,
            resolved_backend=starting_backend,
            models_provisioned=bool(families),
            gpu_enabled=self._gpu_enabled(),
            notes=[
                f"reachable_rungs={[rung.backend for rung in reachable]}",
                f"model_families={families or ['(none — remote only)']}",
                f"model_source={model_source}",
            ],
        )

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------

    def _gpu_enabled(self) -> bool:
        """Whether the GPU is configured for use (enabled and not forced to CPU)."""
        return self._gpu_config.enabled and not self._gpu_config.force_cpu

    def _model_source(self) -> str:
        """The download source, from ``MINERU_MODEL_SOURCE`` or the public default."""
        return os.environ.get(_MODEL_SOURCE_ENV_VAR, _DEFAULT_MODEL_SOURCE)

    def _require_executables(self) -> None:
        """Fail early and clearly if MinerU's command-line tools are not installed."""
        missing = [name for name in _REQUIRED_EXECUTABLES if shutil.which(name) is None]
        if missing:
            raise EngineBootstrapError(
                "MinerU is not fully installed: missing executable(s) "
                f"{', '.join(missing)}. Install MinerU with its API extra so these tools "
                "are on PATH.",
                context={"missing_executables": missing},
            )
