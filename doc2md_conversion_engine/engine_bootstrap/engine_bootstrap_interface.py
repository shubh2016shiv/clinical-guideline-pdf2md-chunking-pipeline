"""
engine_bootstrap/engine_bootstrap_interface.py
===============================================
The contract for preparing a conversion engine BEFORE any timed work begins.

Why this layer exists
---------------------
A timeout only means something if it bounds *work*. The moment a "startup timeout"
also has to cover a one-time, multi-gigabyte model download over the network, it stops
measuring engine health and starts measuring your internet connection — and it will
fire on a perfectly healthy engine that simply hasn't finished downloading yet.

So the slow, unbounded, do-it-once activities — downloading model weights, checking
that the engine's tools are installed, confirming the environment can run it — are
pulled out of the engine lifecycle into this separate **bootstrap** step. Bootstrap is
deliberately *untimed*: it may take seconds (everything cached) or many minutes (first
run, cold cache), and that is fine. Only after bootstrap succeeds do the engine's
``start()`` (load cached models) and ``convert_window()`` (extract pages) run under
timeouts — and now those timeouts bound exactly what they should.

The shape of it
---------------
One method, ``ensure_ready()``: make the engine ready, or explain why it cannot be.
It is idempotent — safe to call repeatedly; it does the download only when something is
actually missing. It returns an ``EngineReadinessReport`` describing what was prepared,
and raises ``EngineBootstrapError`` when the engine cannot be made ready at all (a tool
is not installed, a download failed, the environment is unsuitable).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..contracts.exceptions import PipelineError
from ..contracts.pipeline_domain_types import ExtractionEngine


class EngineBootstrapError(PipelineError):
    """
    Raised when an engine cannot be prepared for work.

    This is distinct from ``EngineStartupError`` on purpose: a startup error means a
    *ready* engine failed to come up within its (now meaningful) timeout, while a
    bootstrap error means the engine could never have started — its tools are missing,
    its models could not be downloaded, or the environment cannot run it. The fix for a
    bootstrap error is operational (install a tool, fix the network, free disk space),
    so the message should say which.
    """


@dataclass(frozen=True)
class EngineReadinessReport:
    """
    A plain summary of what bootstrap prepared, for logs and pre-run reporting.

    It records the facts an operator wants before a long run starts: which engine, the
    concrete backend it will use, whether the model weights are now present locally, and
    whether the GPU is enabled for it. ``notes`` carries any human-readable remarks
    (e.g. "models already cached", "GPU disabled — using CPU backend").
    """

    engine: ExtractionEngine
    resolved_backend: str | None
    models_provisioned: bool
    gpu_enabled: bool
    notes: list[str] = field(default_factory=list)


class AbstractEngineBootstrap(ABC):
    """
    Contract every engine's bootstrap must satisfy.

    Implementations live next to this file (one per engine) and are selected by
    ``EngineBootstrapSelector``. They depend only on configuration and the local
    environment — never on a running engine — so bootstrap can complete fully before an
    engine object is even constructed.
    """

    @property
    @abstractmethod
    def engine_type(self) -> ExtractionEngine:
        """Which engine this bootstrap prepares."""

    @abstractmethod
    async def ensure_ready(self) -> EngineReadinessReport:
        """
        Make the engine ready to run, untimed and idempotent.

        Verifies the engine's tools are installed, downloads any missing model weights
        (however long that takes), and returns an ``EngineReadinessReport``. Does the
        minimum needed: when everything is already present this returns quickly.

        Raises
        ------
        EngineBootstrapError
            If the engine cannot be made ready — a required tool is not installed, a
            model download failed, or the environment is unsuitable.
        """
