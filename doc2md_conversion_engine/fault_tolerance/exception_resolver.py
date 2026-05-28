"""Strict exception-class-name resolution for fault-tolerance configuration."""

from __future__ import annotations

import builtins
import importlib

from ..contracts.exceptions import FaultToleranceConfigurationError


def resolve_exception_class(dotted_name: str) -> type[BaseException]:
    """Resolve a dotted exception class name from configuration.

    This resolver intentionally supports class names only. Predicate callables
    accepted by aiobreaker are code, not serializable YAML configuration.
    """
    module_path, separator, class_name = dotted_name.rpartition(".")
    try:
        candidate = (
            getattr(builtins, class_name)
            if not separator
            else getattr(importlib.import_module(module_path), class_name)
        )
    except (AttributeError, ImportError) as exc:
        raise FaultToleranceConfigurationError(
            f"Cannot resolve configured exception class {dotted_name!r}.",
            context={"exception_class": dotted_name},
        ) from exc

    if not isinstance(candidate, type) or not issubclass(candidate, BaseException):
        raise FaultToleranceConfigurationError(
            f"Configured name {dotted_name!r} does not resolve to an exception class.",
            context={"exception_class": dotted_name},
        )

    return candidate


def resolve_exception_classes(dotted_names: list[str]) -> tuple[type[BaseException], ...]:
    """Resolve configured exception class names while preserving order."""
    return tuple(resolve_exception_class(name) for name in dotted_names)
