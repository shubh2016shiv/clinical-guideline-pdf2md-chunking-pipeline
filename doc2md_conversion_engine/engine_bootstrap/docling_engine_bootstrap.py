"""
engine_bootstrap/docling_engine_bootstrap.py
=============================================
Prepare Docling to run: download the layout, table, and (optional) OCR models.

Docling has the same latent trap as MinerU, just smaller: it downloads its models from
HuggingFace the first time it builds a pipeline, and if that download happens during a
timed startup it can trip the timeout on a healthy engine. So we fetch Docling's models
here, ahead of time and untimed, leaving the engine's ``start()`` to only load them.

What this bootstrap downloads
-----------------------------
Exactly the models Docling will use given the configuration:

  * the **layout** model and the **table-structure** model (always — they read page
    structure and reconstruct tables), and
  * the configured **OCR** model (RapidOCR or EasyOCR) only when OCR is enabled.

It uses Docling's own ``docling-tools models download`` so the model set and cache
location stay consistent with what the engine expects at run time.
"""

from __future__ import annotations

import logging
import shutil

from ..contracts.configurations.docling_engine_config import (
    DoclingEngineConfig,
    DoclingOCRBackend,
)
from ..contracts.configurations.pipeline_config import GPUConfig
from ..contracts.pipeline_domain_types import ExtractionEngine
from .engine_bootstrap_interface import (
    AbstractEngineBootstrap,
    EngineBootstrapError,
    EngineReadinessReport,
)
from .model_provisioning_runner import run_provisioning_command

logger = logging.getLogger(__name__)

# The Docling tool that fetches model weights, and the model names it accepts.
_DOCLING_TOOLS_EXECUTABLE = "docling-tools"
_MODEL_LAYOUT = "layout"
_MODEL_TABLEFORMER = "tableformer"

# Map the configured OCR backend to the model name ``docling-tools`` downloads.
_OCR_BACKEND_TO_MODEL = {
    DoclingOCRBackend.RAPIDOCR: "rapidocr",
    DoclingOCRBackend.EASYOCR: "easyocr",
}


class DoclingEngineBootstrap(AbstractEngineBootstrap):
    """
    Ensure Docling's models are downloaded before any timed run.

    Constructed from the same configuration the engine uses, so it downloads exactly
    the model set the engine will load — including the OCR model only when OCR is on::

        bootstrap = DoclingEngineBootstrap(config.docling_engine, config.gpu)
        report = await bootstrap.ensure_ready()
    """

    def __init__(self, config: DoclingEngineConfig, gpu_config: GPUConfig) -> None:
        self._config = config
        self._gpu_config = gpu_config

    @property
    def engine_type(self) -> ExtractionEngine:
        return ExtractionEngine.DOCLING

    async def ensure_ready(self) -> EngineReadinessReport:
        """Confirm Docling's downloader exists and fetch the configured model set."""
        self._require_executable()

        models = self._models_to_download()
        await run_provisioning_command(
            [_DOCLING_TOOLS_EXECUTABLE, "models", "download", *models],
            description=f"Docling model download ({', '.join(models)})",
        )

        return EngineReadinessReport(
            engine=ExtractionEngine.DOCLING,
            resolved_backend=None,  # Docling has no backend concept; it runs in-process.
            models_provisioned=True,
            gpu_enabled=self._gpu_config.enabled and not self._gpu_config.force_cpu,
            notes=[f"models={'+'.join(models)}", f"ocr_enabled={self._config.ocr_enabled}"],
        )

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------

    def _models_to_download(self) -> list[str]:
        """
        The Docling models to fetch for the current configuration.

        Layout and table-structure are always needed; the OCR model is added only when
        OCR is enabled, so a born-digital-only deployment never pulls OCR weights.
        """
        models = [_MODEL_LAYOUT, _MODEL_TABLEFORMER]
        if self._config.ocr_enabled:
            models.append(_OCR_BACKEND_TO_MODEL[self._config.ocr_backend])
        return models

    def _require_executable(self) -> None:
        """Fail early and clearly if Docling's downloader is not installed."""
        if shutil.which(_DOCLING_TOOLS_EXECUTABLE) is None:
            raise EngineBootstrapError(
                f"Docling is not fully installed: the {_DOCLING_TOOLS_EXECUTABLE!r} tool "
                "is not on PATH. Install Docling so its model downloader is available.",
                context={"missing_executable": _DOCLING_TOOLS_EXECUTABLE},
            )
