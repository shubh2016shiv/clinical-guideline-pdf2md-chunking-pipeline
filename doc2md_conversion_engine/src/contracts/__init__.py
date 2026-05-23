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

# Interfaces
from .conversion_engine_interface import (
    AbstractConversionEngine,
)
from .windowed_checkpoint_store_interface import (
    AbstractCheckpointStore,
    CheckpointState,
    EngineSnapshot,
    WindowRecord,
)

# Exceptions
from .exceptions import (
    AssemblyError,
    CheckpointCorruptedError,
    CheckpointError,
    ConfigurationError,
    DocumentError,
    DocumentTooLargeError,
    EngineError,
    EngineFallbackExhaustedError,
    EngineStartupError,
    EngineTimeoutError,
    FigurePoisonPillError,
    FigureSummarizationError,
    GPUError,
    GPUNotAvailableError,
    PipelineError,
    TokenResolutionTimeoutError,
)

# Configuration
from .configurations.pipeline_config import (
    AssemblyConfig,
    CircuitBreakerConfig,
    CheckpointingConfig,
    DoclingEngineConfig,
    EngineRoutingConfig,
    FaultToleranceConfig,
    FigureSummarizationConfig,
    GPUConfig,
    MinerUEngineConfig,
    ObservabilityConfig,
    PipelineConfig,
    RetryConfig,
    TimeoutsConfig,
    WindowedExtractionConfig,
)
from .configurations.vision_llm_client_config import (
    VisionLLMClientConfig,
    VisionLLMProvider,
)

__all__ = [
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
    "DocumentError",
    "DocumentTooLargeError",
    "EngineError",
    "EngineStartupError",
    "EngineTimeoutError",
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
]
