#!/usr/bin/env python3
"""
Orchestration Package

This package provides comprehensive orchestration capabilities for document
processing, including task management, batch coordination, fault tolerance,
and external integration adapters.

Package Structure:
    - models: Data models for tasks and status
    - configuration: Configuration classes for orchestration
    - resilience: Fault tolerance components (circuit breaker, retry, pooling)
    - metrics: Performance tracking and reporting
    - adapters: External-facing simple and async APIs
    - task_manager: Individual task execution management
    - batch_processor: Batch processing coordination
    - orchestration_client: Main client interface

Main Entry Points:

    1. For Object-Oriented Usage:
       from doc2md_conversion_engine.orchestration import OrchestrationClient
       
       client = OrchestrationClient()
       result = client.process_document("/data/doc.pdf")
       client.cleanup()

    2. For Simple Functional Usage:
       from doc2md_conversion_engine.orchestration import process_document
       
       result = process_document("/data/doc.pdf")

    3. For Async Usage:
       from doc2md_conversion_engine.orchestration import process_document_async
       
       result = await process_document_async("/data/doc.pdf")

    4. For Batch Processing:
       from doc2md_conversion_engine.orchestration import process_documents
       
       results = process_documents([path1, path2, path3])

Exported Classes:
    - OrchestrationClient: Main orchestration interface
    - BatchConfiguration: Configuration for batch processing
    - OrchestrationSettings: System-wide settings
    - ProcessingTask: Task model
    - ProcessingStatus: Task status enum
    - CircuitBreaker: Circuit breaker for fault tolerance
    - RetryHandler: Retry logic handler
    - ProcessorPool: Processor pooling for performance
    - PerformanceTracker: Metrics collection

Exported Functions (Adapters):
    - process_document: Process single document (sync)
    - process_documents: Process batch of documents (sync)
    - process_directory: Process directory of PDFs (sync)
    - process_document_async: Process single document (async)
    - process_documents_async: Process batch (async)
    - process_directory_async: Process directory (async)
"""

# Main client interface
from .orchestration_client import OrchestrationClient

# Configuration classes
from .configuration import (
    BatchConfiguration,
    OrchestrationSettings
)

# Data models
from .models import (
    ProcessingTask,
    ProcessingStatus
)

# Resilience components
from .resilience import (
    CircuitBreaker,
    RetryHandler,
    RetryStrategy,
    ProcessorPool
)

# Metrics
from .metrics import (
    PerformanceTracker,
    PerformanceMetrics
)

# Core components (advanced usage)
from .task_manager import TaskManager
from .batch_processor import BatchProcessor

# Adapter functions (simple usage)
from .adapters import (
    # Simple API
    convert_single_pdf_to_markdown,
    convert_pdf_batch_to_markdown,
    convert_directory_pdfs_to_markdown,
    get_default_conversion_settings,
    
    # Async API
    convert_single_pdf_to_markdown_async,
    convert_pdf_batch_to_markdown_async,
    convert_directory_pdfs_to_markdown_async,
    convert_concurrent_batches_async,
    get_default_conversion_settings_async
)

__all__ = [
    # Main Client
    "OrchestrationClient",
    
    # Configuration
    "BatchConfiguration",
    "OrchestrationSettings",
    
    # Models
    "ProcessingTask",
    "ProcessingStatus",
    
    # Resilience
    "CircuitBreaker",
    "RetryHandler",
    "RetryStrategy",
    "ProcessorPool",
    
    # Metrics
    "PerformanceTracker",
    "PerformanceMetrics",
    
    # Core Components
    "TaskManager",
    "BatchProcessor",
    
    # Simple API Functions
    "convert_single_pdf_to_markdown",
    "convert_pdf_batch_to_markdown",
    "convert_directory_pdfs_to_markdown",
    "get_default_conversion_settings",
    
    # Async API Functions
    "convert_single_pdf_to_markdown_async",
    "convert_pdf_batch_to_markdown_async",
    "convert_directory_pdfs_to_markdown_async",
    "convert_concurrent_batches_async",
    "get_default_conversion_settings_async",
]




