"""Circuit-breaker protection for explicit async operation calls."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import timedelta
from typing import Any, ParamSpec, TypeVar, cast

import aiobreaker

from ..contracts.configurations.pipeline_config import CircuitBreakerConfig
from ..contracts.exceptions import CircuitBreakerOpenError
from .exception_resolver import resolve_exception_classes

P = ParamSpec("P")
T = TypeVar("T")
AiobreakerExclude = tuple[type[Exception] | Callable[[BaseException], bool], ...]


class EngineCircuitBreaker:
    """Domain wrapper around ``aiobreaker`` for explicitly protected calls."""

    def __init__(self, config: CircuitBreakerConfig, component_name: str) -> None:
        self._config = config
        self._component_name = component_name
        excluded_exceptions = resolve_exception_classes(config.exclude_exceptions)
        self._breaker = aiobreaker.CircuitBreaker(
            fail_max=config.fail_max,
            timeout_duration=timedelta(seconds=config.timeout_duration_seconds),
            exclude=cast(AiobreakerExclude, excluded_exceptions),
            name=f"fault_tolerance.{component_name}",
        )

    @property
    def component_name(self) -> str:
        return self._component_name

    @property
    def fail_counter(self) -> int:
        return self._breaker.fail_counter

    @property
    def is_open(self) -> bool:
        return self._breaker.current_state == aiobreaker.CircuitBreakerState.OPEN

    @property
    def state_name(self) -> str:
        return self._breaker.current_state.name

    async def call_async(
        self,
        operation: Callable[P, Coroutine[Any, Any, T]],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        """Execute an async operation through the circuit breaker."""
        try:
            return cast(T, await self._breaker.call_async(operation, *args, **kwargs))
        except aiobreaker.CircuitBreakerError as exc:
            raise CircuitBreakerOpenError(
                f"Circuit breaker is open for component {self._component_name!r}.",
                context={
                    "component_name": self._component_name,
                    "state": self.state_name,
                    "fail_counter": self.fail_counter,
                    "fail_max": self._config.fail_max,
                    "timeout_duration_seconds": self._config.timeout_duration_seconds,
                    "reopen_time": str(exc.reopen_time),
                    "time_remaining_seconds": max(0.0, exc.time_remaining.total_seconds()),
                },
            ) from exc

    def status(self) -> dict[str, Any]:
        """Return a small diagnostic snapshot without exposing aiobreaker internals."""
        return {
            "component_name": self._component_name,
            "state": self.state_name,
            "fail_counter": self.fail_counter,
            "fail_max": self._config.fail_max,
            "is_open": self.is_open,
        }
