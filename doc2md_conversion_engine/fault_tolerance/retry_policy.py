"""Retry policy wrapper for explicit async operations."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec, TypeVar

import stamina

from ..contracts.configurations.pipeline_config import RetryConfig

P = ParamSpec("P")
T = TypeVar("T")
RetryableExceptions = type[Exception] | tuple[type[Exception], ...]


class ExponentialBackoffRetry:
    """Creates retry wrappers from ``RetryConfig`` without changing semantics."""

    def __init__(self, config: RetryConfig) -> None:
        self._config = config

    @property
    def attempts(self) -> int:
        """Total attempts, including the initial call."""
        return self._config.attempts

    def decorate(
        self,
        on: RetryableExceptions,
    ) -> Callable[[Callable[P, Coroutine[Any, Any, T]]], Callable[P, Coroutine[Any, Any, T]]]:
        """Return a retry decorator for async callables."""
        return stamina.retry(
            on=on,
            attempts=self._config.attempts,
            timeout=self._config.timeout_seconds,
            wait_initial=self._config.wait_initial_seconds,
            wait_max=self._config.wait_max_seconds,
            wait_jitter=self._config.wait_jitter_seconds,
            wait_exp_base=self._config.wait_exp_base,
        )

    async def call_async(
        self,
        operation: Callable[P, Coroutine[Any, Any, T]],
        on: RetryableExceptions,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        """Execute an async operation with retry on the configured exception set."""

        @self.decorate(on=on)
        async def retried_operation() -> T:
            return await operation(*args, **kwargs)

        return await retried_operation()
