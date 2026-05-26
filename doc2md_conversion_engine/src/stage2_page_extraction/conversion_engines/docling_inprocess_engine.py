"""
stage2_page_extraction/conversion_engines/docling_inprocess_engine.py
=====================================================================
Stage 2 · the Docling conversion engine (runs in this process).

Docling is the cheap, fast default. It loads its layout and table models directly
into this Python process — no subprocess, no HTTP — which makes it quick to start and
easy to debug. The trade-off is that it shares this process's GPU, so it must never
run at the same time as another GPU engine (the GPU scheduler enforces that).

What this adapter does
----------------------
It wraps Docling's ``DocumentConverter`` behind the pipeline's ``AbstractConversion
Engine`` interface so the rest of Stage 2 can drive it without knowing it is Docling:

  * ``start``  loads the converter once (models into memory / onto the GPU),
  * ``convert_window`` converts a contiguous page range and yields one ``PageResult``
    per page, and
  * ``stop``   drops the converter and frees GPU memory.

Per-page output, not whole-document
------------------------------------
Docling can convert a *page range* and then export Markdown one page at a time, so a
window of pages is converted once and each page is emitted individually. For every
page we ask Docling to mark figure positions with our shared placeholder and we pull
that page's images out of the converted document; the shared page-result builder then
turns figure placeholders into tokens and scans tables. That keeps Docling's output
identical in shape to MinerU's.

Blocking work (model load, conversion) runs in a worker thread via ``asyncio.to_
thread`` so it never stalls the orchestrator's event loop.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...contracts.configurations.docling_engine_config import DoclingEngineConfig
from ...contracts.configurations.pipeline_config import GPUConfig
from ...contracts.conversion_engine_interface import AbstractConversionEngine
from ...contracts.exceptions import EngineError, EngineStartupError
from ...contracts.pipeline_domain_types import ExtractionEngine, PageResult
from ..page_result_builders import FIGURE_PLACEHOLDER_MARKER, RawFigure, RawPage, build_page_result

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter

logger = logging.getLogger(__name__)


class DoclingInProcessEngine(AbstractConversionEngine):
    """
    Convert documents with Docling, in this process, behind the engine interface.

    Constructed per job so it can stamp the document's ``job_id`` into figure tokens::

        engine = DoclingInProcessEngine(config.docling_engine, config.gpu, job.job_id)
        async with engine:
            async for page in engine.convert_window([9, 10, 11], path, out):
                ...
    """

    def __init__(self, config: DoclingEngineConfig, gpu_config: GPUConfig, job_id: str) -> None:
        self._config = config
        self._gpu_config = gpu_config
        self._job_id = job_id
        self._converter: DocumentConverter | None = None

    @property
    def engine_type(self) -> ExtractionEngine:
        return ExtractionEngine.DOCLING

    async def start(self) -> None:
        """
        Build the converter and load its models once; subsequent calls are a no-op.

        Model loading (download + into VRAM) happens here, in ``start()``, on purpose:
        it is one-time warmup that must not count against the per-window extraction
        timeout. Doing it lazily on the first ``convert_window`` would fold a slow
        first-run model download into a timed window and trip the timeout.
        """
        if self._converter is not None:
            return
        try:
            self._converter = await asyncio.to_thread(self._build_and_warm_converter)
        except Exception as exc:  # model download / load / import failure
            raise EngineStartupError(
                "Docling engine failed to initialise (model load or import error).",
                context={"engine": ExtractionEngine.DOCLING.value},
            ) from exc

    async def stop(self) -> None:
        """Drop the converter and free any GPU memory it held. Idempotent."""
        if self._converter is None:
            return
        self._converter = None
        await asyncio.to_thread(self._release_gpu_memory)

    async def is_available(self) -> bool:
        """Docling is ready exactly when its converter is loaded."""
        return self._converter is not None

    async def convert_window(
        self,
        page_numbers: list[int],
        document_path: str,
        output_dir: str,
    ) -> AsyncGenerator[PageResult, None]:
        """
        Convert one contiguous page range and yield a ``PageResult`` per page.

        The whole window is converted once (Docling reads the page range in a single
        pass), then each page's Markdown and figures are extracted and handed to the
        shared builder, in page order.
        """
        if self._converter is None:
            raise EngineError(
                "Docling convert_window called before start().",
                context={"engine": ExtractionEngine.DOCLING.value},
            )
        if not page_numbers:
            return

        window_output_dir = Path(output_dir)
        converted_document = await asyncio.to_thread(
            self._convert_page_range, document_path, page_numbers[0], page_numbers[-1]
        )

        for page_number in page_numbers:
            started_at = time.perf_counter()
            raw_page = await asyncio.to_thread(
                self._extract_raw_page, converted_document, page_number
            )
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            yield build_page_result(
                job_id=self._job_id,
                engine=ExtractionEngine.DOCLING,
                raw_page=raw_page,
                window_output_dir=window_output_dir,
                duration_ms=duration_ms,
            )

    # ------------------------------------------------------------------
    # Docling-specific internals (run inside worker threads)
    # ------------------------------------------------------------------

    def _build_and_warm_converter(self) -> DocumentConverter:
        """
        Build the converter and eagerly load its PDF pipeline models.

        ``initialize_pipeline`` forces the layout and table models to download and
        load now (during ``start()``), so the per-window timeout later covers only
        page extraction.
        """
        from docling.datamodel.base_models import InputFormat

        converter = self._build_converter()
        converter.initialize_pipeline(InputFormat.PDF)
        return converter

    def _build_converter(self) -> DocumentConverter:
        """Construct a Docling ``DocumentConverter`` from the engine config + device."""
        from docling.datamodel.accelerator_options import AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = self._config.ocr_enabled
        pipeline_options.do_table_structure = True
        # Produce actual picture images so figures can be written to disk as PNGs.
        pipeline_options.generate_picture_images = True
        pipeline_options.accelerator_options = AcceleratorOptions(
            device=self._resolve_accelerator_device(),
            num_threads=self._config.num_threads,
        )

        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )

    def _resolve_accelerator_device(self) -> Any:
        """Map the GPU config to a Docling accelerator device (CUDA or CPU)."""
        from docling.datamodel.accelerator_options import AcceleratorDevice

        if not self._gpu_config.enabled or self._gpu_config.force_cpu:
            return AcceleratorDevice.CPU
        return AcceleratorDevice.CUDA

    def _convert_page_range(self, document_path: str, start_page: int, end_page: int) -> Any:
        """Convert an inclusive 1-based page range and return the ``DoclingDocument``."""
        assert self._converter is not None  # guarded by the caller
        result = self._converter.convert(document_path, page_range=(start_page, end_page))
        return result.document

    def _extract_raw_page(self, converted_document: Any, page_number: int) -> RawPage:
        """Pull one page's Markdown (with figure markers) and figure images."""
        from docling_core.types.doc.base import ImageRefMode

        page_markdown = converted_document.export_to_markdown(
            page_no=page_number,
            image_mode=ImageRefMode.PLACEHOLDER,
            image_placeholder=FIGURE_PLACEHOLDER_MARKER,
        )
        figures = self._extract_page_figures(converted_document, page_number)
        return RawPage(page_number=page_number, markdown=page_markdown, figures=figures)

    def _extract_page_figures(self, converted_document: Any, page_number: int) -> list[RawFigure]:
        """Return this page's pictures as PNG-encoded ``RawFigure`` objects, in order."""
        figures: list[RawFigure] = []
        for picture in converted_document.pictures:
            if not any(prov.page_no == page_number for prov in picture.prov):
                continue
            pil_image = picture.get_image(converted_document)
            if pil_image is None:
                continue
            figures.append(RawFigure(image_png_bytes=_encode_png(pil_image)))
        return figures

    @staticmethod
    def _release_gpu_memory() -> None:
        """Best-effort release of cached CUDA memory after the converter is dropped."""
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            logger.debug("docling.gpu_release_skipped", exc_info=True)


def _encode_png(pil_image: Any) -> bytes:
    """Encode a PIL image to PNG bytes."""
    buffer = io.BytesIO()
    pil_image.save(buffer, format="PNG")
    return buffer.getvalue()
