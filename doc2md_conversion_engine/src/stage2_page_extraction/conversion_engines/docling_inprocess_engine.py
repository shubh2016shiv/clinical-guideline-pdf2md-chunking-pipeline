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

  * ``start``  builds the converter and validates Docling imports once,
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

Blocking conversion work runs in a worker thread via ``asyncio.to_thread`` so it
never stalls the orchestrator's event loop.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
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

_DOCLING_LAYOUT_REPO_ID = "docling-project/docling-layout-heron"
_DOCLING_LAYOUT_REVISION = "main"
_REQUIRED_DOCLING_LAYOUT_FILES = (
    "model.safetensors",
    "config.json",
    "preprocessor_config.json",
)


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
        Build the converter once; subsequent calls are a no-op.

        Heavy model loading happens during the first conversion window, under the
        engine lifecycle's exclusive GPU lease and the configured window timeout. That
        keeps startup cheap and prevents a model warmup from running outside Stage 2's
        GPU ownership boundary.
        """
        if self._converter is not None:
            return
        try:
            self._ensure_required_models_available()
            self._converter = self._build_converter()
        except EngineStartupError:
            raise
        except Exception as exc:  # model download / load / import failure
            raise EngineStartupError(
                "Docling engine failed to initialise.",
                context={
                    "engine": ExtractionEngine.DOCLING.value,
                    "allow_model_downloads": self._config.allow_model_downloads,
                },
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
        with _huggingface_download_policy(allow_downloads=self._config.allow_model_downloads):
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

    def _ensure_required_models_available(self) -> None:
        """
        Fail clearly when Docling's required local models are missing.

        Letting ``snapshot_download`` run inside conversion makes Stage 2 look hung
        when the host has no route to Hugging Face/Xet. Runtime downloads can still be
        enabled explicitly for development machines.
        """
        if self._config.allow_model_downloads:
            return

        missing_files = _missing_huggingface_cache_files(
            repo_id=_DOCLING_LAYOUT_REPO_ID,
            revision=_DOCLING_LAYOUT_REVISION,
            filenames=_REQUIRED_DOCLING_LAYOUT_FILES,
        )
        if not missing_files:
            return

        incomplete_files = _incomplete_huggingface_cache_files(_DOCLING_LAYOUT_REPO_ID)
        raise EngineStartupError(
            "Docling layout model is not fully available in the local Hugging Face cache. "
            "Pre-download the model or set docling_engine.allow_model_downloads=true "
            "for a development run with network access.",
            context={
                "engine": ExtractionEngine.DOCLING.value,
                "repo_id": _DOCLING_LAYOUT_REPO_ID,
                "revision": _DOCLING_LAYOUT_REVISION,
                "missing_files": missing_files,
                "incomplete_files": incomplete_files,
            },
        )

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


def _missing_huggingface_cache_files(
    *,
    repo_id: str,
    revision: str,
    filenames: tuple[str, ...],
) -> list[str]:
    """Return required model files absent from the local Hugging Face cache."""
    from huggingface_hub import try_to_load_from_cache

    missing: list[str] = []
    for filename in filenames:
        cached_path = try_to_load_from_cache(repo_id, filename, revision=revision)
        if cached_path is None or not Path(cached_path).is_file():
            missing.append(filename)
    return missing


def _incomplete_huggingface_cache_files(repo_id: str) -> list[str]:
    """Return partial downloads for ``repo_id`` from the default Hugging Face cache."""
    cache_root = Path.home() / ".cache" / "huggingface" / "hub"
    repo_cache_dir = cache_root / f"models--{repo_id.replace('/', '--')}"
    if not repo_cache_dir.exists():
        return []
    return sorted(str(path) for path in repo_cache_dir.glob("blobs/*.incomplete"))


@contextmanager
def _huggingface_download_policy(*, allow_downloads: bool) -> Iterator[None]:
    """
    Keep Hugging Face offline during conversion unless runtime downloads are allowed.

    The environment variable is restored afterwards so this engine does not leak a
    process-wide policy into unrelated code.
    """
    if allow_downloads:
        yield
        return

    previous_offline = os.environ.get("HF_HUB_OFFLINE")
    previous_xet = os.environ.get("HF_HUB_DISABLE_XET")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    try:
        yield
    finally:
        _restore_env_var("HF_HUB_OFFLINE", previous_offline)
        _restore_env_var("HF_HUB_DISABLE_XET", previous_xet)


def _restore_env_var(name: str, value: str | None) -> None:
    """Restore or remove one environment variable."""
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
