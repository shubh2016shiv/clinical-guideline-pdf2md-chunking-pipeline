"""
contracts/exceptions.py
=======================
Domain exception hierarchy for the doc2md conversion pipeline.

All exceptions inherit from ``PipelineError`` so callers can catch the
entire domain with a single ``except PipelineError`` when they need a
broad safety net, while still being able to handle specific failure modes
(e.g. ``except GPUNotAvailableError``) for targeted recovery.

Hierarchy
---------
PipelineError
├── ConfigurationError
├── DocumentError
│   └── DocumentTooLargeError
├── EngineError
│   ├── EngineStartupError
│   ├── EngineTimeoutError
│   └── EngineFallbackExhaustedError
├── GPUError
│   └── GPUNotAvailableError
├── CheckpointError
│   └── CheckpointCorruptedError
├── FigureSummarizationError
│   └── FigurePoisonPillError
└── AssemblyError
    └── TokenResolutionTimeoutError
"""


class PipelineError(Exception):
    """
    Base class for all doc2md pipeline exceptions.

    Carries an optional ``context`` dict so structured loggers can attach
    per-event metadata (page number, engine name, document id, etc.)
    without parsing the string message.

    Example::

        raise EngineTimeoutError(
            "MinerU window timed out",
            context={"page_range": "9-16", "engine": "mineru"},
        )
    """

    def __init__(self, message: str, context: dict | None = None) -> None:
        super().__init__(message)
        # Structured metadata attached to this exception instance.
        # Always a dict (never None) so callers can safely do ``e.context.get(...)``.
        self.context: dict = context or {}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class ConfigurationError(PipelineError):
    """Raised when settings are missing, invalid, or mutually inconsistent."""


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


class DocumentError(PipelineError):
    """Raised when the source document itself is the problem."""


class DocumentTooLargeError(DocumentError):
    """
    Raised when the document exceeds the configured page or file-size ceiling.

    The pipeline refuses to start rather than risk an out-of-memory crash
    mid-way through a 500-page document.
    """


# ---------------------------------------------------------------------------
# Engine  (conversion engines: MinerU, Docling)
# ---------------------------------------------------------------------------


class EngineError(PipelineError):
    """Base class for conversion engine failures."""


class EngineStartupError(EngineError):
    """
    Raised when an engine fails to initialise within the configured timeout.

    For MinerU this means the FastAPI subprocess did not become healthy in
    time. For Docling it means the in-process model load failed.
    """


class EngineTimeoutError(EngineError):
    """
    Raised when a single windowed extraction batch exceeds
    ``fault_tolerance.timeouts.engine_window_seconds``.

    The circuit breaker (aiobreaker) records this as a failure. After
    ``fault_tolerance.circuit_breaker.fail_max`` consecutive timeouts it
    opens the breaker and routes the remaining windows to the fallback engine.

    Jargon — circuit breaker: a resilience pattern borrowed from electrical
    engineering. When too many failures occur in a row, the breaker "opens"
    (like tripping a fuse) and stops sending work to the failing component,
    giving it time to recover before trying again.
    """


class EngineFallbackExhaustedError(EngineError):
    """
    Raised when both the primary engine (MinerU) and the fallback engine
    (Docling) have failed for the same extraction window.

    At this point the pipeline cannot make progress without human
    intervention (e.g. the GPU is dead, the document is corrupt).
    """


# ---------------------------------------------------------------------------
# GPU
# ---------------------------------------------------------------------------


class GPUError(PipelineError):
    """Base class for GPU-related failures."""


class GPUNotAvailableError(GPUError):
    """
    Raised when GPU acceleration is required but either no CUDA device is
    detected or the available VRAM is below ``gpu.max_vram_mb``.

    When ``engine_routing.conversion_engine`` is ``auto`` the pipeline
    catches this and retries with the CPU backend instead of crashing.
    """


# ---------------------------------------------------------------------------
# Checkpointing
# ---------------------------------------------------------------------------


class CheckpointError(PipelineError):
    """Base class for checkpoint persistence failures."""


class CheckpointCorruptedError(CheckpointError):
    """
    Raised when a checkpoint file exists on disk but cannot be deserialised
    (truncated by a kill -9, JSON parse error, schema version mismatch).

    Recovery strategy: delete the corrupted checkpoint and restart from
    page 0.  Losing a partial run is far better than blocking forever on
    unreadable state.

    Jargon — checkpoint: a snapshot of pipeline progress written to disk
    after each window so that a crash or kill -9 can be resumed from the
    last completed window rather than restarting from scratch.
    """


# ---------------------------------------------------------------------------
# Figure summarisation  (Stage 3 — vision LLM batch processing)
# ---------------------------------------------------------------------------


class FigureSummarizationError(PipelineError):
    """
    Raised when the vision LLM (e.g. QVQ-Max) fails to summarise a figure.

    The ``context`` dict should include ``token`` (the ``${FIG:...}``
    placeholder string) so the assembler can substitute a degraded
    placeholder and continue rather than blocking the whole document.
    """


class FigurePoisonPillError(FigureSummarizationError):
    """
    Raised after a specific figure has failed
    ``figure_summarization.figure_retries`` consecutive times.

    The figure is permanently skipped — the poison-pill pattern prevents
    one broken image from stalling the entire pipeline indefinitely.

    Jargon — poison pill: a message or item that, after a configurable
    number of failed processing attempts, is deliberately discarded so the
    consumer (worker pool) can move on rather than retrying forever.
    """


# ---------------------------------------------------------------------------
# Assembly  (Stage 4)
# ---------------------------------------------------------------------------


class AssemblyError(PipelineError):
    """Base class for markdown assembly failures."""


class TokenResolutionTimeoutError(AssemblyError):
    """
    Raised when a ``${FIG:...}`` placeholder token is still unresolved
    after ``fault_tolerance.timeouts.figure_token_resolution_seconds``.

    The assembler does NOT block — it emits the degraded placeholder from
    ``assembly.degraded_mode_placeholder`` and continues so the document
    always completes.

    Jargon — token-based deferred resolution: figures are extracted fast
    and replaced with short placeholder strings (tokens) during GPU
    extraction. A separate async worker pool resolves those tokens by
    sending the images to the vision LLM. The assembler waits for each
    token before writing the final markdown for that page.
    """
