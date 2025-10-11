#!/usr/bin/env python3
"""
Simple API Adapter Module

This module provides a simple, function-based API for document processing
orchestration. It's designed for external modules that need straightforward
document processing without managing orchestration objects directly.

Purpose:
    - Provide simple function-based interface for common operations
    - Hide orchestration complexity from external callers
    - Enable quick integration with minimal code
    - Support single document and batch processing

Target Users:
    - External modules needing document processing
    - Quick prototyping and testing
    - Simple integration scenarios
    - Users preferring functional over object-oriented style

Usage Pattern:
    Import functions and call directly with paths and options.
    No need to create or manage orchestration objects.
"""

import logging
from typing import List, Optional, Dict, Any
from pathlib import Path

from ..orchestration_client import OrchestrationClient
from ..configuration.batch_configuration import BatchConfiguration

from doc2md_conversion_engine.models.config import DocumentProcessingConfig
from doc2md_conversion_engine.engine.document_processor import DocumentProcessor

# Create module logger
logger = logging.getLogger(__name__)


def convert_single_pdf_to_markdown(
    pdf_path: str,
    output_path: Optional[str] = None,
    output_filename: Optional[str] = None,
    max_retries: int = 3,
    gemini_api_key: Optional[str] = None,
    enable_gemini: bool = False,
    **config_options
):
    """
    Process a single PDF document with automatic orchestration.

    Simple interface for processing one document. Creates orchestration
    client internally, processes the document, and cleans up automatically.

    Args:
        pdf_path: Path to PDF file to process
        output_path: Optional directory for output files
        output_filename: Optional custom output filename (no extension)
        max_retries: Maximum retry attempts on failure (default: 3)
        gemini_api_key: Google Gemini API key for figure summarization (optional)
        enable_gemini: Whether to enable Gemini AI for figure summarization (default: False)
        **config_options: Additional BatchConfiguration parameters

    Returns:
        DocumentResult object with processing outputs

    Raises:
        ProcessingError: If document processing fails
        ValidationError: If inputs are invalid

    Example:
        >>> # Process single document
        >>> result = convert_single_pdf_to_markdown("/data/document.pdf")
        >>> print(f"Output: {result.markdown_path}")
        >>>
        >>> # With custom output location
        >>> result = convert_single_pdf_to_markdown(
        ...     "/data/document.pdf",
        ...     output_path="/output",
        ...     output_filename="processed_doc"
        ... )
    """

    # Initialize processing configuration with Gemini settings
    # Pass output_path if provided to ensure correct directory structure
    config_kwargs = {
        'gemini_api_key': gemini_api_key or "GEMINI_API_KEY_HERE",
        'enable_gemini': enable_gemini or True,  # Enable Gemini by default or use provided value
        'extract_tables': True,
        'write_table_csv': True
    }
    
    # Add output_path to config if provided
    if output_path:
        config_kwargs['output_dir'] = output_path
    
    processing_config = DocumentProcessingConfig(**config_kwargs)

    # Create optimized batch configuration
    batch_config = BatchConfiguration(
        max_retries_per_task=max_retries,
        enable_progress_reporting=config_options.pop('show_progress', True),
        **config_options
    )

    # Initialize document processor with configuration
    processor = DocumentProcessor(processing_config)

    # Process document using context manager for proper cleanup
    with OrchestrationClient(batch_config=batch_config) as client:
        # Set optimized processor in task manager
        if hasattr(client, 'task_manager'):
            client.task_manager.processor = processor
            logger.info(f"Injected configured processor with Gemini enabled={processor.config.enable_gemini}, API key present={bool(processor.config.gemini_api_key)}")

        # Process document and return results
        return client.orchestrate_single_document(
            pdf_path=pdf_path,
            output_path=output_path,
            output_filename=output_filename
        )


def convert_pdf_batch_to_markdown(
    pdf_paths: List[str],
    output_path: Optional[str] = None,
    max_concurrent: int = 5,
    max_retries: int = 3,
    show_progress: bool = True,
    **config_options
) -> List[Dict[str, Any]]:
    """
    Process multiple PDF documents as a batch.
    
    Simple interface for batch processing. Creates orchestration client,
    processes all documents with configured concurrency, and returns results.
    
    Args:
        pdf_paths: List of paths to PDF files
        output_path: Optional base directory for output files
        max_concurrent: Maximum concurrent tasks (default: 5)
        max_retries: Maximum retry attempts per document (default: 3)
        show_progress: Show progress bar during processing (default: True)
        **config_options: Additional BatchConfiguration parameters
    
    Returns:
        List of dictionaries with processing results and status
        Each dict contains:
            - pdf_path: Input file path
            - success: Boolean indicating if processing succeeded
            - result: DocumentResult object (if successful)
            - error: Error message (if failed)
            - attempts: Number of processing attempts made
    
    Example:
        >>> # Process multiple documents
        >>> paths = ["/data/doc1.pdf", "/data/doc2.pdf", "/data/doc3.pdf"]
        >>> results = convert_pdf_batch_to_markdown(paths, max_concurrent=3)
        >>> 
        >>> # Check results
        >>> successful = [r for r in results if r['success']]
        >>> print(f"Processed {len(successful)}/{len(results)} documents")
        >>> 
        >>> # Handle failures
        >>> for result in results:
        ...     if not result['success']:
        ...         print(f"Failed: {result['pdf_path']}: {result['error']}")
    """
    # Create configuration
    config = BatchConfiguration(
        max_concurrent_tasks=max_concurrent,
        max_retries_per_task=max_retries,
        enable_progress_reporting=show_progress,
        **config_options
    )
    
    # Create orchestration client and process documents
    with OrchestrationClient(batch_config=config) as client:
        tasks = client.orchestrate_document_batch(
            pdf_paths=pdf_paths,
            output_path=output_path,
            use_async=True
        )
        
        # Convert tasks to simple result dictionaries
        results = []
        for task in tasks:
            result_dict = {
                'pdf_path': task.pdf_path,
                'success': task.result is not None,
                'result': task.result,
                'error': task.error,
                'attempts': task.attempts,
                'duration': task.duration
            }
            results.append(result_dict)
        
        return results


def convert_directory_pdfs_to_markdown(
    directory_path: str,
    file_pattern: str = "*.pdf",
    output_path: Optional[str] = None,
    max_concurrent: int = 5,
    max_retries: int = 3,
    show_progress: bool = True,
    **config_options
) -> Dict[str, Any]:
    """
    Process all PDF files in a directory.
    
    Discovers PDF files matching pattern and processes them as a batch,
    returning comprehensive summary of results.
    
    Args:
        directory_path: Path to directory containing PDF files
        file_pattern: Glob pattern for file matching (default: "*.pdf")
        output_path: Optional base directory for output files
        max_concurrent: Maximum concurrent tasks (default: 5)
        max_retries: Maximum retry attempts per document (default: 3)
        show_progress: Show progress bar during processing (default: True)
        **config_options: Additional BatchConfiguration parameters
    
    Returns:
        Dictionary with comprehensive processing summary:
            - total_files: Total number of files processed
            - successful: Number of successful processings
            - failed: Number of failed processings
            - success_rate: Percentage of successful processings
            - results: List of individual result dictionaries
            - failed_files: List of failed file paths with errors
    
    Example:
        >>> # Process all PDFs in directory
        >>> summary = convert_directory_pdfs_to_markdown("/data/pdfs/")
        >>> print(f"Success rate: {summary['success_rate']:.1f}%")
        >>> print(f"Processed {summary['successful']}/{summary['total_files']}")
        >>> 
        >>> # Handle failures
        >>> for failure in summary['failed_files']:
        ...     print(f"Failed: {failure['path']}: {failure['error']}")
    """
    # Validate directory
    directory = Path(directory_path)
    if not directory.exists() or not directory.is_dir():
        from ...exceptions import ValidationError
        raise ValidationError(f"Invalid directory: {directory_path}")
    
    # Find PDF files
    pdf_files = sorted(directory.glob(file_pattern))
    pdf_paths = [str(f) for f in pdf_files]
    
    if not pdf_paths:
        return {
            'total_files': 0,
            'successful': 0,
            'failed': 0,
            'success_rate': 0.0,
            'results': [],
            'failed_files': []
        }
    
    # Process all files
    results = convert_pdf_batch_to_markdown(
        pdf_paths=pdf_paths,
        output_path=output_path,
        max_concurrent=max_concurrent,
        max_retries=max_retries,
        show_progress=show_progress,
        **config_options
    )
    
    # Generate summary
    successful_count = sum(1 for r in results if r['success'])
    failed_count = len(results) - successful_count
    
    summary = {
        'total_files': len(results),
        'successful': successful_count,
        'failed': failed_count,
        'success_rate': (successful_count / len(results)) * 100 if results else 0.0,
        'results': results,
        'failed_files': [
            {'path': r['pdf_path'], 'error': r['error']}
            for r in results if not r['success']
        ]
    }
    
    return summary


def get_default_conversion_settings() -> Dict[str, Any]:
    """
    Get default configuration parameters.
    
    Returns dictionary of default configuration values that can be
    customized and passed to processing functions.
    
    Returns:
        Dictionary with default configuration parameters
    
    Example:
        >>> # Get defaults and customize
        >>> config = get_default_conversion_settings()
        >>> config['max_concurrent_tasks'] = 10
        >>> config['enable_processor_pooling'] = True
        >>> 
        >>> # Use with processing function
        >>> results = convert_pdf_batch_to_markdown(paths, **config)
    """
    default_config = BatchConfiguration()
    return {
        'max_concurrent': default_config.max_concurrent_tasks,
        'max_retries': default_config.max_retries_per_task,
        'retry_delay': default_config.retry_delay_seconds,
        'enable_exponential_backoff': default_config.exponential_backoff,
        'task_timeout': default_config.task_timeout_seconds,
        'enable_processor_pooling': default_config.enable_processor_pooling,
        'processor_pool_size': default_config.processor_pool_size,
        'show_progress': default_config.enable_progress_reporting
    }

