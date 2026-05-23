"""Named async timeout guards that raise pipeline-domain exceptions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from ..contracts.configurations.pipeline_config import TimeoutsConfig
from ..contracts.exceptions import (
    EngineTimeoutError,
    FigureSummarizationError,
    PipelineError,
    TokenResolutionTimeoutError,
)


class AsyncOperationTimeoutGuard:
    """Factory for named ``asyncio.timeout`` contexts from ``TimeoutsConfig``."""

    def __init__(self, config: TimeoutsConfig) -> None:
        self._config = config

    @asynccontextmanager
    async def engine_window(
        self,
        *,
        window_index: int | None = None,
        component_name: str | None = None,
    ) -> AsyncGenerator[None, None]:
        deadline = self._config.engine_window_seconds
        context = {
            "operation": "engine_window",
            "deadline_seconds": deadline,
            "window_index": window_index,
            "component_name": component_name,
        }
        async with self._timeout(deadline, EngineTimeoutError, context):
            yield

    @asynccontextmanager
    async def llm_batch_call(
        self,
        *,
        batch_size: int | None = None,
    ) -> AsyncGenerator[None, None]:
        deadline = self._config.llm_batch_call_seconds
        context = {
            "operation": "llm_batch_call",
            "deadline_seconds": deadline,
            "batch_size": batch_size,
        }
        async with self._timeout(deadline, FigureSummarizationError, context):
            yield

    @asynccontextmanager
    async def gpu_acquire(self) -> AsyncGenerator[None, None]:
        deadline = self._config.gpu_acquire_seconds
        context = {"operation": "gpu_acquire", "deadline_seconds": deadline}
        async with self._timeout(deadline, EngineTimeoutError, context):
            yield

    @asynccontextmanager
    async def figure_token_resolution(
        self,
        *,
        token: str | None = None,
        page_number: int | None = None,
    ) -> AsyncGenerator[None, None]:
        deadline = self._config.figure_token_resolution_seconds
        context = {
            "operation": "figure_token_resolution",
            "deadline_seconds": deadline,
            "token": token,
            "page_number": page_number,
        }
        async with self._timeout(deadline, TokenResolutionTimeoutError, context):
            yield

    @asynccontextmanager
    async def custom(
        self,
        deadline_seconds: float,
        operation_name: str,
        exc_class: type[PipelineError],
    ) -> AsyncGenerator[None, None]:
        context = {"operation": operation_name, "deadline_seconds": deadline_seconds}
        async with self._timeout(deadline_seconds, exc_class, context):
            yield

    @asynccontextmanager
    async def _timeout(
        self,
        deadline_seconds: float,
        exc_class: type[PipelineError],
        context: dict,
    ) -> AsyncGenerator[None, None]:
        timeout = asyncio.timeout(deadline_seconds)
        try:
            async with timeout:
                yield
        except TimeoutError as exc:
            if not timeout.expired():
                raise
            raise exc_class(
                f"Operation {context['operation']!r} timed out after {deadline_seconds:.0f} seconds.",
                context=context,
            ) from exc
