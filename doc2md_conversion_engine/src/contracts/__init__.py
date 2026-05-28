"""
contracts/
==========
Public interface of the contracts module.

Import from here rather than from individual sub-modules so internal
re-organisations never break callers::

    from doc2md_conversion_engine.src.contracts import (
        PipelineConfig,
        PageResult,
        ConversionJob,
        ExtractionEngine,
        AbstractConversionEngine,
        AbstractCheckpointStore,
    )
"""

# Domain types
# Configuration
from .configurations.ollama_vision_client_config import (
    OllamaVisionClientConfig,
)
from .configurations.pipeline_config import (
    AssemblyConfig,
    CheckpointingConfig,
    CircuitBreakerConfig,
    DoclingEngineConfig,
    EngineRoutingConfig,
    FaultToleranceConfig,
    FigureSummarizationConfig,
    FigureVisionProvider,
    GPUConfig,
    MinerUEngineConfig,
    ObservabilityConfig,
    PipelineConfig,
    RetryConfig,
    TimeoutsConfig,
    WindowedExtractionConfig,
)
from .configurations.vision_llm_client_config import (
    VisionLLMApiType,
    VisionLLMClientConfig,
    VisionLLMImageBudget,
    VisionLLMProvider,
)
from .figure_summarization_interfaces import (
    AbstractFigureDedupCache,
    AbstractFigureSummaryStore,
    AbstractFigureWorkQueue,
    AbstractVisionFigureClient,
)
from .figure_summarization_types import (
    ALLOWED_RENDERING_STRATEGIES_BY_FIGURE_TYPE,
    FIGURE_SUMMARY_JSON_SCHEMA,
    DocumentDomain,
    FigureSummary,
    FigureType,
    LegibilityLevel,
    RenderingStrategy,
)

# Interfaces
from .conversion_engine_interface import (
    AbstractConversionEngine,
)

# Exceptions
from .exceptions import (
    AssemblyError,
    CheckpointCorruptedError,
    CheckpointError,
    CircuitBreakerOpenError,
    ConfigurationError,
    DocumentError,
    DocumentTooLargeError,
    EngineError,
    EngineFallbackExhaustedError,
    EngineStartupError,
    EngineTimeoutError,
    FaultToleranceConfigurationError,
    FigurePoisonPillError,
    FigureSummarizationError,
    GPUError,
    GPUNotAvailableError,
    PipelineError,
    TokenResolutionTimeoutError,
)
from .pipeline_domain_types import (
    ConversionJob,
    ConversionSummary,
    DocumentType,
    EngineClassification,
    ExtractionEngine,
    Figure,
    MinerUBackend,
    PageProfile,
    PageResult,
    Table,
)
from .windowed_checkpoint_store_interface import (
    AbstractCheckpointStore,
    CheckpointState,
    EngineSnapshot,
    WindowRecord,
)

__all__ = [
    # Stage 3 interfaces
    "AbstractVisionFigureClient",
    "AbstractFigureDedupCache",
    "AbstractFigureSummaryStore",
    "AbstractFigureWorkQueue",
    # Stage 3 domain types
    "FigureSummary",
    "FigureType",
    "RenderingStrategy",
    "LegibilityLevel",
    "DocumentDomain",
    "FIGURE_SUMMARY_JSON_SCHEMA",
    "ALLOWED_RENDERING_STRATEGIES_BY_FIGURE_TYPE",
    "FigureVisionProvider",
    "OllamaVisionClientConfig",
    # Domain types
    "ConversionJob",
    "ConversionSummary",
    "DocumentType",
    "EngineClassification",
    "ExtractionEngine",
    "Figure",
    "MinerUBackend",
    "PageProfile",
    "PageResult",
    "Table",
    # Interfaces
    "AbstractConversionEngine",
    "AbstractCheckpointStore",
    "CheckpointState",
    "EngineSnapshot",
    "WindowRecord",
    # Exceptions
    "PipelineError",
    "ConfigurationError",
    "FaultToleranceConfigurationError",
    "DocumentError",
    "DocumentTooLargeError",
    "EngineError",
    "EngineStartupError",
    "EngineTimeoutError",
    "CircuitBreakerOpenError",
    "EngineFallbackExhaustedError",
    "GPUError",
    "GPUNotAvailableError",
    "CheckpointError",
    "CheckpointCorruptedError",
    "FigureSummarizationError",
    "FigurePoisonPillError",
    "AssemblyError",
    "TokenResolutionTimeoutError",
    # Configuration
    "PipelineConfig",
    "EngineRoutingConfig",
    "MinerUEngineConfig",
    "DoclingEngineConfig",
    "WindowedExtractionConfig",
    "CheckpointingConfig",
    "GPUConfig",
    "FigureSummarizationConfig",
    "FaultToleranceConfig",
    "CircuitBreakerConfig",
    "RetryConfig",
    "TimeoutsConfig",
    "AssemblyConfig",
    "ObservabilityConfig",
    "VisionLLMClientConfig",
    "VisionLLMProvider",
    "VisionLLMApiType",
    "VisionLLMImageBudget",
]
