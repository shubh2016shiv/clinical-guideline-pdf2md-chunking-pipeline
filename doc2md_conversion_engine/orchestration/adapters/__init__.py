#!/usr/bin/env python3
"""
Adapters Package

This package provides external-facing adapters for easy integration with
the orchestration system. Adapters offer simplified interfaces for common
use cases without requiring deep knowledge of the orchestration internals.

Adapter Types:
    1. Simple API: Function-based synchronous interface
    2. Async API: Function-based asynchronous interface

Exported Functions (Simple API):
    - process_document: Process single document synchronously
    - process_documents: Process batch of documents
    - process_directory: Process all PDFs in directory
    - get_default_configuration: Get default config parameters

Exported Functions (Async API):
    - process_document_async: Process single document asynchronously
    - process_documents_async: Process batch asynchronously
    - process_directory_async: Process directory asynchronously
    - process_concurrent_batches: Process multiple batches concurrently

Usage Examples:

    # Simple synchronous usage
    from doc2md_conversion_engine.orchestration.adapters import process_document
    result = process_document("/data/document.pdf")

    # Batch processing
    from doc2md_conversion_engine.orchestration.adapters import process_documents
    results = process_documents([path1, path2, path3], max_concurrent=5)

    # Async usage
    from doc2md_conversion_engine.orchestration.adapters import process_document_async
    result = await process_document_async("/data/document.pdf")

    # Directory processing
    from doc2md_conversion_engine.orchestration.adapters import process_directory
    summary = process_directory("/data/pdfs/", max_concurrent=10)
"""

# Import simple API functions
from .synchronous_processor import (
    convert_single_pdf_to_markdown,
    convert_pdf_batch_to_markdown,
    convert_directory_pdfs_to_markdown,
    get_default_conversion_settings
)

# Import async API functions
from .asynchronous_processor import (
    process_document_async,
    process_documents_async,
    process_directory_async,
    process_concurrent_batches
)

__all__ = [
    # Simple API
    "convert_single_pdf_to_markdown",
    "convert_pdf_batch_to_markdown",
    "convert_directory_pdfs_to_markdown",
    "get_default_conversion_settings",
    
    # Async API
    "process_document_async",
    "process_documents_async",
    "process_directory_async",
    "process_concurrent_batches",
]




