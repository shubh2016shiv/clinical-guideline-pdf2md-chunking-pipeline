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

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..pipeline_domain_types import MinerUBackend


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
        default=MinerUBackend.VLM,
        description=(
            "Processing backend to use.  "
            "VLM = GPU-accelerated Vision-Language Model (highest accuracy).  "
            "PIPELINE = CPU-only rule-based pipeline (no GPU required)."
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
