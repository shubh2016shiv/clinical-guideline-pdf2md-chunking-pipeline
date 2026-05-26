"""
stage2_page_extraction/conversion_engines/resilient_conversion_engine.py
========================================================================
Stage 2 · run the chosen engine resiliently, falling back when it fails.

This is the clever piece of the engine layer. It does not convert anything itself —
it *wraps* a primary engine (the one Stage 1 chose) and a fallback engine (Docling),
and makes the pair behave like a single, dependable engine. Because it implements the
same ``AbstractConversionEngine`` interface, the orchestrator above it just sees "an
engine" and never has to know that retries, timeouts, or a fallback ever happened.

What "resilient" means here, concretely
----------------------------------------
Every window sent to the primary engine is protected by the three fault-tolerance
primitives the project already provides:

  * a **timeout** so one stuck window cannot hang the whole run,
  * **retries** with backoff for transient failures within that window, and
  * a **circuit breaker** that, after repeated failures, stops hammering a broken
    primary and routes work to the fallback instead.

When the primary cannot deliver a window — it errors past its retries, or the breaker
is open — the whole window is re-run on the fallback engine, and every page from the
fallback is marked ``is_degraded`` so operators can measure the accuracy impact.

Why a whole window at a time
----------------------------
The primary's pages are collected for the entire window before any are emitted. If
the primary failed halfway, we must be able to re-run the window on the fallback
without double-emitting the pages the primary already produced. Treating the window
as the atomic unit (which is also the checkpoint unit) makes fallback clean and
duplicate-free.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from ...contracts.conversion_engine_interface import AbstractConversionEngine
from ...contracts.exceptions import (
    CircuitBreakerOpenError,
    EngineError,
    EngineFallbackExhaustedError,
)
from ...contracts.pipeline_domain_types import ExtractionEngine, PageResult
from ...fault_tolerance import (
    AsyncOperationTimeoutGuard,
    EngineCircuitBreaker,
    ExponentialBackoffRetry,
)

logger = logging.getLogger(__name__)


class ResilientConversionEngine(AbstractConversionEngine):
    """
    Compose a primary and fallback engine into one fault-tolerant engine.

    Built by ``conversion_engine_factory`` with the fault-tolerance primitives
    already wired. ``fallback`` is ``None`` when the primary is itself the fallback
    engine (Docling chosen directly) — in that case a primary failure has nowhere to
    degrade to and surfaces as ``EngineFallbackExhaustedError``.
    """

    def __init__(
        self,
        *,
        primary: AbstractConversionEngine,
        fallback: AbstractConversionEngine | None,
        circuit_breaker: EngineCircuitBreaker,
        retry: ExponentialBackoffRetry,
        timeout_guard: AsyncOperationTimeoutGuard,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._circuit_breaker = circuit_breaker
        self._retry = retry
        self._timeout_guard = timeout_guard
        self._fallback_started = False

    @property
    def engine_type(self) -> ExtractionEngine:
        """The intended (primary) engine; per-page results carry the actual engine used."""
        return self._primary.engine_type

    async def start(self) -> None:
        """Start the primary engine. The fallback is started lazily, only if needed."""
        await self._primary.start()

    async def stop(self) -> None:
        """Stop both engines. Idempotent — safe even if the fallback never started."""
        await self._primary.stop()
        if self._fallback is not None and self._fallback_started:
            await self._fallback.stop()
            self._fallback_started = False

    async def is_available(self) -> bool:
        """Available while the primary is usable, or the breaker is open but a fallback exists."""
        if not self._circuit_breaker.is_open:
            return await self._primary.is_available()
        return self._fallback is not None

    async def convert_window(
        self,
        page_numbers: list[int],
        document_path: str,
        output_dir: str,
    ) -> AsyncGenerator[PageResult, None]:
        """
        Convert one window, transparently degrading to the fallback on primary failure.

        If the breaker is already open we go straight to the fallback. Otherwise we
        attempt the primary (timeout + retry + breaker); any engine failure or an open
        breaker triggers a full-window fallback run. Pages are yielded only once the
        producing engine has delivered the whole window.
        """
        if not page_numbers:
            return

        if self._circuit_breaker.is_open:
            logger.info(
                "stage2.engine.breaker_open primary=%s -> using fallback",
                self._primary.engine_type.value,
            )
            window_pages = await self._convert_window_via_fallback(
                page_numbers, document_path, output_dir
            )
        else:
            try:
                window_pages = await self._convert_window_via_primary(
                    page_numbers, document_path, output_dir
                )
            except (EngineError, CircuitBreakerOpenError) as primary_failure:
                logger.warning(
                    "stage2.engine.degraded primary=%s reason=%s -> falling back",
                    self._primary.engine_type.value,
                    type(primary_failure).__name__,
                )
                window_pages = await self._convert_window_via_fallback(
                    page_numbers, document_path, output_dir, primary_failure=primary_failure
                )

        for page_result in window_pages:
            yield page_result

    # ------------------------------------------------------------------
    # Primary path (timeout + retry + circuit breaker)
    # ------------------------------------------------------------------

    async def _convert_window_via_primary(
        self,
        page_numbers: list[int],
        document_path: str,
        output_dir: str,
    ) -> list[PageResult]:
        """
        Run the whole window on the primary, guarded by timeout, retry, and breaker.

        Composition (inside-out): a single timeout-bounded attempt → retried on
        transient ``EngineError`` → the retried operation counted by the circuit
        breaker, so a window that fails even after retries trips the breaker once.
        """

        async def _timed_attempt() -> list[PageResult]:
            async with self._timeout_guard.engine_window(
                component_name=self._primary.engine_type.value
            ):
                return [
                    page_result
                    async for page_result in self._primary.convert_window(
                        page_numbers, document_path, output_dir
                    )
                ]

        async def _retried_attempt() -> list[PageResult]:
            return await self._retry.call_async(_timed_attempt, on=EngineError)

        return await self._circuit_breaker.call_async(_retried_attempt)

    # ------------------------------------------------------------------
    # Fallback path
    # ------------------------------------------------------------------

    async def _convert_window_via_fallback(
        self,
        page_numbers: list[int],
        document_path: str,
        output_dir: str,
        *,
        primary_failure: BaseException | None = None,
    ) -> list[PageResult]:
        """
        Run the whole window on the fallback engine, marking every page degraded.

        Raises ``EngineFallbackExhaustedError`` when no fallback exists (the primary
        was already the fallback engine), chaining the original primary failure.
        """
        if self._fallback is None:
            raise EngineFallbackExhaustedError(
                f"Primary engine {self._primary.engine_type.value!r} failed and no "
                "fallback engine is configured for this document.",
                context={"primary_engine": self._primary.engine_type.value},
            ) from primary_failure

        await self._ensure_fallback_started()
        fallback_pages = [
            page_result
            async for page_result in self._fallback.convert_window(
                page_numbers, document_path, output_dir
            )
        ]
        # PageResult is frozen; produce degraded copies rather than mutating.
        return [page_result.model_copy(update={"is_degraded": True}) for page_result in fallback_pages]

    async def _ensure_fallback_started(self) -> None:
        """Start the fallback engine once, on first use, to avoid loading two engines upfront."""
        if self._fallback is not None and not self._fallback_started:
            await self._fallback.start()
            self._fallback_started = True
