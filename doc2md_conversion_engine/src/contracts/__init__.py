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
from .configurations.pipeline_config import (
    AssemblyConfig,
    CheckpointingConfig,
    CircuitBreakerConfig,
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
]
