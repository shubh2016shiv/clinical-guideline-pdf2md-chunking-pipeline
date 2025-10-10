#!/usr/bin/env python3
"""
Document Processing Engine

A professional document processing system for clinical guidelines, providing
PDF to Markdown conversion with intelligent structure analysis, figure extraction,
and comprehensive orchestration capabilities.

Features:
- PDF processing with structure preservation
- Figure and table extraction
- Batch processing with fault tolerance
- Concurrent document processing
- Comprehensive error handling
- Progress tracking and metrics collection
- Synchronous and asynchronous APIs

Main Components:
- Orchestration: Task management and batch coordination
- Engine: Core document processing capabilities
- Models: Data structures and configuration
- Exceptions: Error handling
"""

from __future__ import annotations

__version__ = "2.0.0"
__author__ = "Shubham Singh"
__description__ = "Document Processing Engine"

# Import exceptions
from .exceptions import (
    GuidelineProcessorError,
    ConfigurationError,
    ProcessingError,
    ValidationError
)

# Import data models
from .models.config import DocumentProcessingConfig
from .models.document import DocumentResult, ProcessingMetadata

# Import orchestration components
from .orchestration import (
    # Main client
    OrchestrationClient,
    
    # Configuration
    BatchConfiguration,
    OrchestrationSettings,
    
    # Simple API functions
    convert_single_pdf_to_markdown,
    convert_pdf_batch_to_markdown,
    convert_directory_pdfs_to_markdown,
    get_default_conversion_settings,
    
    # Async API functions
    process_document_async,
    process_documents_async,
    process_directory_async,
    process_concurrent_batches
)

# Import high-level entry points
from .trigger_doc_to_markdown_conversion import (
    start_single_doc_processing,
    start_batch_doc_processing,
    start_docs_processing_from_directory
)

# Public API
__all__ = [
    # Core data models
    "DocumentProcessingConfig",
    "DocumentResult",
    "ProcessingMetadata",
    
    # Exceptions
    "GuidelineProcessorError",
    "ConfigurationError",
    "ProcessingError",
    "ValidationError",
    
    # Orchestration client
    "OrchestrationClient",
    "BatchConfiguration",
    "OrchestrationSettings",
    
    # Simple API functions
    "convert_single_pdf_to_markdown",
    "convert_pdf_batch_to_markdown",
    "convert_directory_pdfs_to_markdown",
    "get_default_conversion_settings",
    
    # Async API functions
    "process_document_async",
    "process_documents_async",
    "process_directory_async",
    "process_concurrent_batches",
    
    # High-level entry points
    "start_single_doc_processing",
    "start_batch_doc_processing",
    "start_docs_processing_from_directory",
]