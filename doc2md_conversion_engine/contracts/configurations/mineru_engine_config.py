"""
contracts/configurations/mineru_engine_config.py
=================================================
Configuration model for the MinerU conversion engine.

MinerU runs as a managed subprocess — it starts its own FastAPI server
(``mineru-api``) that the pipeline communicates with over HTTP on localhost.
This isolation is intentional: MinerU manages its own GPU memory via vLLM
and must not share a PyTorch CUDA context with Docling.

All values are read from the ``mineru_engine`` section of ``settings.yaml``
and can be overridden at runtime via environment variables prefixed with
``MINERU_`` (e.g. ``MINERU_API_PORT=9000``).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..pipeline_domain_types import MinerUBackend


class BackendRung(BaseModel):
    """
    One rung of MinerU's capability ladder — a backend plus what it requires.

    The ladder is an *ordered* list of these (highest capability first). At run time
    the engine keeps only the rungs this hardware/config can actually reach and walks
    them top-down, stepping to the next rung when one fails. The ORDER is a contract:
    it is fixed in ``settings.yaml`` so an upgrade never silently reshuffles the
    fallback sequence a deployment already depends on.
    """

    model_config = ConfigDict(frozen=True)

    backend: str = Field(
        ...,
        description=(
            "The exact MinerU backend name (e.g. 'vlm-auto-engine', 'vlm-http-client', "
            "'pipeline'). Must be a name MinerU accepts — an unknown name makes MinerU "
            "skip the file."
        ),
    )
    min_vram_mb: int = Field(
        default=0,
        ge=0,
        description=(
            "Minimum usable GPU VRAM (MiB) this rung needs. A rung is skipped at "
            "selection time when usable VRAM is below this. 0 means 'always reachable' "
            "(the CPU-capable floor)."
        ),
    )
    requires_server_url: bool = Field(
        default=False,
        description=(
            "True for remote rungs (the *-http-client backends): the rung is skipped "
            "unless a ``server_url`` is configured."
        ),
    )


def _default_backend_ladder() -> list[BackendRung]:
    """
    The default capability ladder, highest quality first.

    vlm-auto-engine (local GPU, 95+ accuracy, needs ~8 GB VRAM)
        ↓
    vlm-http-client (remote VLM, 95+ at ~2 GB local — skipped unless server_url set)
        ↓
    pipeline (rule-based, 85+ accuracy, CPU-capable — the guaranteed floor)

    http-client sits ABOVE pipeline on purpose: when a remote VLM server is available
    it delivers VLM-quality output at tiny local cost, so it is strictly preferable to
    the pipeline floor.
    """
    return [
        BackendRung(backend="vlm-auto-engine", min_vram_mb=8192),
        BackendRung(backend="vlm-http-client", min_vram_mb=2048, requires_server_url=True),
        BackendRung(backend="pipeline", min_vram_mb=0),
    ]


class MinerUEngineConfig(BaseSettings):
    """
    Settings for the MinerU engine subprocess.

    ``BaseSettings`` (pydantic-settings) reads values in this priority order:
      1. Explicit keyword arguments passed to the constructor (highest priority).
      2. Environment variables prefixed with ``MINERU_``.
      3. The ``mineru_engine`` section of ``settings.yaml``.
      4. Field defaults defined below (lowest priority).

    This means a developer can override any value on the command line without
    editing the YAML, e.g.::

        MINERU_BACKEND=pipeline python -m entrypoints.convert_document_to_markdown_cli ...
    """

    model_config = SettingsConfigDict(
        env_prefix="MINERU_",
        # YAML is loaded by PipelineConfig and injected here; individual
        # engine configs intentionally do NOT load YAML themselves to avoid
        # reading the file multiple times.
        extra="ignore",
    )

    backend: MinerUBackend = Field(
        default=MinerUBackend.AUTO,
        description=(
            "How the backend is chosen.  "
            "AUTO = walk ``backend_ladder``: pick the highest rung this hardware can "
            "reach and step down on failure (the recommended, hardware-portable mode).  "
            "VLM / PIPELINE = pin to that single backend and disable the ladder."
        ),
    )

    backend_ladder: list[BackendRung] = Field(
        default_factory=_default_backend_ladder,
        description=(
            "Ordered capability ladder used when ``backend`` is AUTO. Highest quality "
            "first; the engine keeps the rungs reachable on this hardware and steps "
            "down on failure. The ORDER is a stability contract — fix it before deploy."
        ),
    )

    server_url: str | None = Field(
        default=None,
        description=(
            "Base URL of a remote MinerU VLM server (for the *-http-client rungs). "
            "When unset, those rungs are skipped. e.g. 'http://10.0.0.5:30000'."
        ),
    )

    api_host: str = Field(
        default="127.0.0.1",
        description=(
            "Host the mineru-api subprocess binds to.  "
            "Always localhost — the subprocess is not exposed externally."
        ),
    )

    api_port: int = Field(
        default=8888,
        ge=1024,
        le=65535,
        description="Port the mineru-api FastAPI subprocess listens on.",
    )

    startup_timeout_seconds: int = Field(
        default=60,
        ge=10,
        description=(
            "Maximum seconds to wait for the subprocess to become healthy "
            "(GET /health returns 200 OK).  Raise EngineStartupError if exceeded."
        ),
    )

    window_timeout_seconds: int = Field(
        default=300,
        ge=30,
        description=(
            "Maximum seconds for a single extraction window before the circuit "
            "breaker records a failure and optionally trips to Docling fallback."
        ),
    )

    vlm_model: str = Field(
        default="opendatalab/MinerU-VLM",
        description=(
            "HuggingFace model ID for the Vision-Language Model backend.  "
            "Only used when ``backend`` is VLM."
        ),
    )

    @property
    def api_base_url(self) -> str:
        """Convenience property: the full HTTP base URL of the subprocess API."""
        return f"http://{self.api_host}:{self.api_port}"
