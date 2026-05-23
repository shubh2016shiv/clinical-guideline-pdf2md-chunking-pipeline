"""
contracts/configurations/pipeline_config.py
============================================
Top-level pipeline configuration, composed from all section configs.

This is the single object the orchestrator and all stages receive.
It reads ``settings.yaml`` once at startup, validates every value, and
exposes strongly-typed sub-configs so callers never parse raw dicts.

Settings priority (highest → lowest)
--------------------------------------
1. Constructor keyword arguments (useful in tests).
2. Environment variables (e.g. ``PIPELINE_GPU__FORCE_CPU=true``).
3. ``settings.yaml`` (the human-editable file in ``src/``).
4. Field defaults defined in each config class.

Usage
-----
::

    from doc2md_conversion_engine.src.contracts.configurations.pipeline_config import (
        PipelineConfig,
    )

    config = PipelineConfig()          # reads settings.yaml automatically
    config = PipelineConfig(           # override a specific section in tests
        gpu=GPUConfig(force_cpu=True)
    )

Section ↔ settings.yaml mapping
---------------------------------
``engine_routing``      →  engine_routing.*
``mineru_engine``       →  mineru_engine.*
``docling_engine``      →  docling_engine.*
``windowed_extraction`` →  windowed_extraction.*
``checkpointing``       →  checkpointing.*
``gpu``                 →  gpu.*
``figure_summarization``→  figure_summarization.*
``fault_tolerance``     →  fault_tolerance.*
``assembly``            →  assembly.*
``observability``       →  observability.*
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from .docling_engine_config import DoclingEngineConfig
from .mineru_engine_config import MinerUEngineConfig
from .vision_llm_client_config import VisionLLMClientConfig

# Absolute path to the settings file co-located with this src/ tree.
_SETTINGS_YAML_PATH = Path(__file__).parent.parent.parent / "settings.yaml"


# ---------------------------------------------------------------------------
# Section configs (plain pydantic BaseModel, not BaseSettings)
# ---------------------------------------------------------------------------
# These are nested under PipelineConfig.  We use plain BaseModel here so
# that only PipelineConfig (the root) handles YAML and env-var loading.
# ---------------------------------------------------------------------------

class ConversionEngineChoice(StrEnum):
    """
    How the pipeline selects a conversion engine.

    AUTO
        Run the complexity classifier (Stage 1) and route to the best engine.
        Recommended for production.
    MINERU
        Always use MinerU, regardless of document complexity.
    DOCLING
        Always use Docling (useful for quick tests or simple documents).
    """

    AUTO = "auto"
    MINERU = "mineru"
    DOCLING = "docling"


class ComplexityWeightsConfig(BaseModel):
    """
    Per-feature weights used by the complexity classifier to score a document.

    Higher weight = this feature pushes the score further towards MinerU VLM.
    Scores are summed across all pages and divided by total page count.
    """

    multi_column_page: float = Field(default=3.0, ge=0.0)
    diagram_heavy_page: float = Field(default=5.0, ge=0.0)
    large_table_page: float = Field(default=4.0, ge=0.0)
    low_text_density_page: float = Field(
        default=2.0,
        ge=0.0,
        description="Applied to pages with text_density < 0.02.",
    )


class EngineRoutingConfig(BaseModel):
    """Controls which engine is selected and how complexity is scored."""

    conversion_engine: ConversionEngineChoice = Field(
        default=ConversionEngineChoice.AUTO,
        description=(
            "Engine selection mode.  "
            "auto = run the classifier and choose the best engine.  "
            "mineru / docling = bypass the classifier."
        ),
    )

    complexity_threshold_complex: float = Field(
        default=2.0,
        ge=0.0,
        description="Complexity score at or above which MinerU VLM is selected.",
    )

    complexity_threshold_moderate: float = Field(
        default=0.5,
        ge=0.0,
        description=(
            "Complexity score at or above which MinerU pipeline (CPU) is selected.  "
            "Scores below this threshold route to Docling."
        ),
    )

    complexity_weights: ComplexityWeightsConfig = Field(
        default_factory=ComplexityWeightsConfig
    )


class WindowedExtractionConfig(BaseModel):
    """
    Controls memory-bounded streaming extraction through the document.

    Jargon — windowed extraction: instead of loading all pages at once
    (OOM risk) or one page at a time (slow), the pipeline processes pages
    in fixed-size batches (windows).  Each window is extracted, checkpointed,
    and its results yielded downstream before the next window begins.
    """

    window_size: int = Field(
        default=8,
        ge=1,
        description="Number of pages processed per GPU window.  Tune to fit within VRAM budget.",
    )

    max_concurrent_windows: int = Field(
        default=2,
        ge=1,
        description=(
            "Maximum number of windows that can be in-flight simultaneously.  "
            "Docling (in-process) supports > 1 via its internal ThreadPool.  "
            "MinerU (subprocess) serialises windows internally."
        ),
    )

    checkpoint_interval_pages: int = Field(
        default=4,
        ge=1,
        description="fsync a checkpoint to disk every N completed pages.",
    )


class CheckpointingConfig(BaseModel):
    """Persistence settings for the windowed checkpoint store."""

    checkpoint_dir: str = Field(
        default=".checkpoints",
        description=(
            "Directory (relative to the job output_dir) where checkpoint JSON "
            "files are written.  One file per document, named by job_id."
        ),
    )

    enabled: bool = Field(
        default=True,
        description=(
            "Disable checkpointing for short test runs where resumability is "
            "not needed.  When False the pipeline always starts from page 1."
        ),
    )


class GPUConfig(BaseModel):
    """GPU device selection and VRAM budget enforcement."""

    enabled: bool = Field(
        default=True,
        description="When False the pipeline behaves as if no GPU is present.",
    )

    force_cpu: bool = Field(
        default=False,
        description=(
            "Force CPU-only mode even when a GPU is available.  "
            "Useful for reproducibility testing or memory-constrained environments."
        ),
    )

    cuda_device_id: int = Field(
        default=0,
        ge=0,
        description="CUDA device index to use.  Ignored when ``force_cpu`` is True.",
    )

    max_vram_mb: int = Field(
        default=5500,
        ge=1024,
        description=(
            "Hard VRAM ceiling in megabytes.  The pipeline refuses to start an "
            "engine that would exceed this budget, preventing out-of-memory crashes."
        ),
    )


class FigureSummarizationConfig(BaseModel):
    """
    Settings for Stage 3 — async batch vision LLM processing of figures.

    Jargon — worker pool: instead of spawning one thread per figure
    (which would create hundreds of threads), a fixed-size pool of workers
    (``worker_pool_size``) dequeues figures from a bounded queue and sends
    them to the LLM in batches.  This provides controlled concurrency with
    automatic backpressure.

    Jargon — backpressure: when the queue reaches ``max_queue_size``, the
    extraction stage blocks instead of adding more items.  This prevents
    unbounded memory growth if the LLM is slower than extraction.
    """

    enabled: bool = Field(
        default=True,
        description=(
            "When False figures are replaced with the degraded placeholder "
            "immediately, skipping all LLM calls.  Useful for fast development "
            "runs where figure summaries are not needed."
        ),
    )

    worker_pool_size: int = Field(
        default=3,
        ge=1,
        description="Fixed number of concurrent vision LLM workers.",
    )

    batch_size: int = Field(
        default=5,
        ge=1,
        description=(
            "Number of images bundled into a single API call.  "
            "Lower values suit QVQ-Max (chain-of-thought per image is slower); "
            "raise to 10 for faster models like Qwen3-VL-Flash."
        ),
    )

    max_queue_size: int = Field(
        default=100,
        ge=1,
        description="Maximum figures in the async queue before backpressure kicks in.",
    )

    rate_limit_rpm: int = Field(
        default=60,
        ge=1,
        description="Maximum API requests per minute.  Matched to DashScope's default limit.",
    )

    batch_timeout_seconds: float = Field(
        default=60.0,
        gt=0.0,
        description=(
            "Maximum seconds to wait for a single LLM batch call.  "
            "Raised to 60 s for QVQ-Max because chain-of-thought reasoning "
            "takes longer than standard generation."
        ),
    )

    token_resolution_timeout_seconds: float = Field(
        default=300.0,
        gt=0.0,
        description=(
            "Maximum seconds the assembler waits for a specific ``${FIG:...}`` "
            "token to resolve before substituting the degraded placeholder."
        ),
    )

    figure_retries: int = Field(
        default=3,
        ge=1,
        description=(
            "How many times to retry a failing figure before raising "
            "``FigurePoisonPillError`` and permanently skipping it."
        ),
    )

    deduplication_enabled: bool = Field(
        default=True,
        description=(
            "Skip LLM calls for figures whose SHA-256 is already in the cache.  "
            "Clinical guidelines frequently reuse the same diagram across sections; "
            "this can reduce LLM calls by ~30 %."
        ),
    )

    deduplication_cache_dir: str = Field(
        default=".figure_cache",
        description=(
            "Directory where the SHA-256 → LLM summary cache is persisted.  "
            "Survives across runs so repeated runs of the same document are fast."
        ),
    )

    vision_llm: VisionLLMClientConfig = Field(default_factory=VisionLLMClientConfig)


class CircuitBreakerConfig(BaseModel):
    """
    Settings passed to ``aiobreaker.CircuitBreaker``.

    The breaker only observes operations explicitly executed through the
    fault-tolerance module. An open breaker blocks those protected calls until
    ``timeout_duration_seconds`` allows a recovery probe.
    """

    fail_max: int = Field(
        default=3,
        ge=1,
        description=(
            "Consecutive protected-call failures before the circuit breaker opens. "
            "Mapped to ``aiobreaker`` ``fail_max``."
        ),
    )

    timeout_duration_seconds: int = Field(
        default=60,
        ge=10,
        description=(
            "Seconds the breaker stays OPEN before attempting a recovery probe.  "
            "Mapped to ``aiobreaker`` ``timeout_duration`` (as a timedelta)."
        ),
    )

    exclude_exceptions: list[str] = Field(
        default_factory=lambda: ["asyncio.CancelledError"],
        description=(
            "Fully-qualified exception class names that should NOT count as "
            "circuit-breaker failures. Callable predicates are not supported "
            "in YAML configuration."
        ),
    )


class RetryConfig(BaseModel):
    """
    Settings passed to ``stamina.retry()``.

    ``stamina`` uses exponential backoff with jitter:
    ``delay = min(wait_max, wait_initial * wait_exp_base^attempt) + random(0, wait_jitter)``
    """

    attempts: int = Field(
        default=3,
        ge=1,
        description="Total attempts, including the initial call. Maps to ``stamina`` ``attempts``.",
    )

    timeout_seconds: float = Field(
        default=90.0,
        gt=0.0,
        description="Total time budget across all attempts.  Maps to ``stamina`` ``timeout``.",
    )

    wait_initial_seconds: float = Field(
        default=1.0,
        gt=0.0,
        description="Delay before the first retry.  Maps to ``stamina`` ``wait_initial``.",
    )

    wait_max_seconds: float = Field(
        default=30.0,
        gt=0.0,
        description="Backoff ceiling.  Maps to ``stamina`` ``wait_max``.",
    )

    wait_jitter_seconds: float = Field(
        default=2.0,
        ge=0.0,
        description=(
            "Random jitter added per attempt to prevent thundering-herd.  "
            "Maps to ``stamina`` ``wait_jitter``."
        ),
    )

    wait_exp_base: float = Field(
        default=2.0,
        gt=1.0,
        description="Exponential growth factor.  Maps to ``stamina`` ``wait_exp_base``.",
    )


class TimeoutsConfig(BaseModel):
    """
    Per-operation hard deadlines enforced with ``asyncio.timeout()`` (stdlib).

    No external library is needed — ``asyncio.timeout()`` is built into
    Python 3.11+ and is the recommended approach for Python 3.12.
    """

    engine_window_seconds: float = Field(
        default=300.0,
        gt=0.0,
        description="Max time for a single GPU extraction window.",
    )

    llm_batch_call_seconds: float = Field(
        default=60.0,
        gt=0.0,
        description="Max time for one vision LLM batch API call.",
    )

    gpu_acquire_seconds: float = Field(
        default=30.0,
        gt=0.0,
        description="Max time to wait for exclusive GPU context acquisition.",
    )

    figure_token_resolution_seconds: float = Field(
        default=300.0,
        gt=0.0,
        description="Max time the assembler waits for a ${FIG:...} token to resolve.",
    )


class FaultToleranceConfig(BaseModel):
    """Groups all fault-tolerance sub-configs for passing to stages."""

    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)


class AssemblyConfig(BaseModel):
    """Settings for Stage 4 — final markdown assembly and disk output."""

    output_flush_threshold_bytes: int = Field(
        default=1_048_576,
        ge=1,
        description=(
            "Assembled markdown is flushed to disk when the in-memory buffer "
            "reaches this size (default 1 MB).  Keeps peak RAM usage bounded."
        ),
    )

    degraded_mode_placeholder: str = Field(
        default="[Figure: processing failed — see original document]",
        description=(
            "String substituted in place of any ``${FIG:...}`` token that could "
            "not be resolved (timeout or poison-pill).  Must make it clear to a "
            "clinical reader that a figure was present but not summarised."
        ),
    )


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ObservabilityConfig(BaseModel):
    """Controls structured logging, metrics, and health reporting."""

    log_level: LogLevel = Field(
        default=LogLevel.INFO,
        description="Minimum log level emitted to stdout.",
    )

    structured_logging: bool = Field(
        default=True,
        description=(
            "When True each page event is emitted as a JSON object so log "
            "aggregators (e.g. Loki, Splunk) can parse fields directly."
        ),
    )

    metrics_enabled: bool = Field(
        default=True,
        description="Enable Prometheus-style metrics collection.",
    )

    health_check_enabled: bool = Field(
        default=True,
        description="Enable the /health status reporter.",
    )


# ---------------------------------------------------------------------------
# Root config — the single object passed to the orchestrator
# ---------------------------------------------------------------------------


class PipelineConfig(BaseSettings):
    """
    Root configuration object for the entire pipeline.

    Reads ``settings.yaml`` (located in the same ``src/`` directory as this
    file) via pydantic-settings' ``YamlConfigSettingsSource`` and composes
    all section configs into one strongly-typed object.

    Instantiate once at pipeline startup::

        config = PipelineConfig()

    Override the YAML path for testing::

        config = PipelineConfig(_yaml_file=Path("tests/fixtures/settings_test.yaml"))
    """

    model_config = SettingsConfigDict(
        env_prefix="PIPELINE_",
        env_nested_delimiter="__",   # e.g. PIPELINE_GPU__FORCE_CPU=true
        extra="ignore",
    )

    # Allow the YAML path to be overridden (e.g. in tests).
    _yaml_file: Path = _SETTINGS_YAML_PATH

    # Section configs — each maps to a top-level key in settings.yaml.
    engine_routing: EngineRoutingConfig = Field(default_factory=EngineRoutingConfig)
    mineru_engine: MinerUEngineConfig = Field(default_factory=MinerUEngineConfig)
    docling_engine: DoclingEngineConfig = Field(default_factory=DoclingEngineConfig)
    windowed_extraction: WindowedExtractionConfig = Field(
        default_factory=WindowedExtractionConfig
    )
    checkpointing: CheckpointingConfig = Field(default_factory=CheckpointingConfig)
    gpu: GPUConfig = Field(default_factory=GPUConfig)
    figure_summarization: FigureSummarizationConfig = Field(
        default_factory=FigureSummarizationConfig
    )
    fault_tolerance: FaultToleranceConfig = Field(default_factory=FaultToleranceConfig)
    assembly: AssemblyConfig = Field(default_factory=AssemblyConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """
        Load order: constructor args → env vars → settings.yaml → defaults.

        ``YamlConfigSettingsSource`` is placed last so env vars always win
        over the YAML file, which in turn wins over field defaults.
        """
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=_SETTINGS_YAML_PATH),
        )

    @model_validator(mode="after")
    def _validate_threshold_ordering(self) -> PipelineConfig:
        """
        Ensure complexity thresholds are logically ordered:
        complex threshold must be strictly above moderate threshold.
        """
        er = self.engine_routing
        if er.complexity_threshold_complex <= er.complexity_threshold_moderate:
            raise ValueError(
                f"complexity_threshold_complex ({er.complexity_threshold_complex}) "
                f"must be greater than complexity_threshold_moderate "
                f"({er.complexity_threshold_moderate})."
            )
        return self
