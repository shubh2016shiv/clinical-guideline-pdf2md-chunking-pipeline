"""
contracts/conversion_engine_interface.py
=========================================
Abstract base class (interface) that every conversion engine must implement.

Why an interface?
-----------------
The architecture uses the Strategy pattern for engine selection: MinerU and
Docling are two algorithms for the same job.  By programming against this
interface the rest of the pipeline (the circuit-breaker router, the windowed
orchestrator) never knows which engine is running — it just calls the same
three methods.  Swapping engines or adding a third one (e.g. Marker) only
requires a new class that implements this interface.

Jargon — Strategy pattern: a design pattern where a family of algorithms
(here: conversion engines) are encapsulated behind a common interface so the
caller can swap them at runtime without changing its own code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from .pipeline_domain_types import (
    ExtractionEngine,
    PageResult,
)


class AbstractConversionEngine(ABC):
    """
    Contract that MinerU and Docling engines must satisfy.

    Lifecycle
    ---------
    1. ``start()``          — initialise the engine adapter or start its subprocess.
    2. ``convert_window()`` — extract one window of pages; yield PageResults.
    3. ``stop()``           — release GPU memory and shut down subprocess.

    The engine is always used as an async context manager so the pipeline
    guarantees ``stop()`` is called even on errors::

        async with engine:
            async for page_result in engine.convert_window(pages, gpu_ctx):
                ...
    """

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def engine_type(self) -> ExtractionEngine:
        """
        Which engine this instance represents.

        Used by the circuit-breaker router and structured logger to tag
        every page result and metric with the correct engine name.
        """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def start(self) -> None:
        """
        Initialise the engine and make it ready to accept conversion windows.

        For MinerU: starts the ``mineru-api`` FastAPI subprocess and waits
        until its ``/health`` endpoint returns 200 OK.

        For Docling: builds the in-process converter and validates configuration.
        Heavy model loading may happen during the first window so it remains inside
        the engine lifecycle's GPU ownership boundary.

        Raises
        ------
        EngineStartupError
            If the engine does not become healthy within the configured
            startup timeout.
        """

    @abstractmethod
    async def stop(self) -> None:
        """
        Release all resources held by this engine.

        For MinerU: sends SIGTERM to the subprocess and waits for it to exit,
        then calls ``torch.cuda.empty_cache()`` to free VRAM.

        For Docling: unloads models from memory / VRAM.

        This method must be idempotent — calling it on an already-stopped
        engine must not raise.
        """

    @abstractmethod
    async def is_available(self) -> bool:
        """
        Non-blocking health check.

        Returns True if the engine is running and able to accept work.
        Used by the circuit-breaker router before routing a window.

        For MinerU: performs a lightweight GET /health on the subprocess API.
        For Docling: checks that models are loaded in memory.
        """

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    @abstractmethod
    def convert_window(
        self,
        page_numbers: list[int],
        document_path: str,
        output_dir: str,
    ) -> AsyncGenerator[PageResult, None]:
        """
        Extract a contiguous window of pages and yield one ``PageResult``
        per page as each page finishes — do not wait for the whole window.

        This is an async generator so callers receive pages as a stream
        rather than waiting for the entire batch.  The orchestrator can
        start checkpointing and feeding the figure queue while the engine
        is still processing later pages in the same window.

        Parameters
        ----------
        page_numbers:
            The 1-based page numbers to process in this window.
            Always a contiguous range (e.g. [9, 10, 11, 12, 13, 14, 15, 16]).
        document_path:
            Absolute path to the source document as a string (engines accept
            paths, not file handles, because MinerU runs in a subprocess).
        output_dir:
            Directory where this window's extracted page markdown files and
            figure PNGs should be written.

        Yields
        ------
        PageResult
            One per page in ``page_numbers``, in page order.

        Raises
        ------
        EngineTimeoutError
            If the engine does not finish the window within the configured
            ``fault_tolerance.timeouts.engine_window_seconds``.
        EngineError
            For any other engine-level failure within the window.
        """

    # ------------------------------------------------------------------
    # Async context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> AbstractConversionEngine:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()
