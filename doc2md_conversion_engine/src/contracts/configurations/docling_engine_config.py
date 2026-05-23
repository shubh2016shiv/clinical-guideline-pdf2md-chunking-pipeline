"""
contracts/configurations/docling_engine_config.py
==================================================
Configuration model for the Docling conversion engine.

Docling runs in-process — its models are loaded directly into the Python
process (no subprocess, no HTTP).  This makes it faster to start and
simpler to debug than MinerU, but it means Docling and MinerU cannot both
hold GPU memory at the same time.  The pipeline enforces this via the
exclusive GPU context manager.

Docling is the fallback engine: it handles simple documents directly and
steps in automatically when the MinerU circuit breaker trips.

All values are read from the ``docling_engine`` section of ``settings.yaml``
and can be overridden via environment variables prefixed with ``DOCLING_``.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DoclingOCRBackend(str, Enum):
    """
    OCR engine used by Docling for scanned pages or low-quality PDFs.

    RAPIDOCR
        Lightweight, pure-Python, no external binary required.
        Good default for most documents.

    EASYOCR
        PyTorch-based, more accurate on noisy or rotated text,
        but slower and requires a GPU for best performance.

    Jargon — OCR (Optical Character Recognition): the process of converting
    images of printed text into machine-readable characters.  Needed when
    a PDF is a scanned image rather than containing embedded text.
    """

    RAPIDOCR = "rapidocr"
    EASYOCR = "easyocr"


class DoclingTableModel(str, Enum):
    """
    Neural model used for table structure detection.

    TABLEFORMER
        IBM Research's TableFormer (~0.5 GB VRAM).
        Best for multi-row-span and merged-cell tables common in clinical
        guidelines.
    """

    TABLEFORMER = "tableformer"


class DoclingEngineConfig(BaseSettings):
    """
    Settings for the Docling in-process engine.

    ``BaseSettings`` reads values in this priority order:
      1. Constructor keyword arguments.
      2. Environment variables prefixed with ``DOCLING_``.
      3. The ``docling_engine`` section of ``settings.yaml`` (injected by PipelineConfig).
      4. Field defaults.
    """

    model_config = SettingsConfigDict(
        env_prefix="DOCLING_",
        extra="ignore",
    )

    num_threads: int = Field(
        default=4,
        ge=1,
        description=(
            "Size of the ThreadPoolExecutor used to parallelise page processing "
            "within a single Docling window.  "
            "Set to 1 to disable intra-window parallelism (useful for debugging)."
        ),
    )

    ocr_enabled: bool = Field(
        default=True,
        description=(
            "Enable OCR for scanned pages or pages where embedded text is absent.  "
            "Disable to speed up processing of born-digital PDFs."
        ),
    )

    ocr_backend: DoclingOCRBackend = Field(
        default=DoclingOCRBackend.RAPIDOCR,
        description="OCR engine to use when ``ocr_enabled`` is True.",
    )

    table_structure_model: DoclingTableModel = Field(
        default=DoclingTableModel.TABLEFORMER,
        description=(
            "Neural model used to detect table structure (rows, columns, spans).  "
            "TableFormer (~0.5 GB VRAM) is the recommended choice for clinical tables."
        ),
    )
