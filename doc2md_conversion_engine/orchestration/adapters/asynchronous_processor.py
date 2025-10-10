#!/usr/bin/env python3
"""
Async API Adapter Module

This module provides asynchronous function-based API for document processing
orchestration. Designed for async/await contexts where non-blocking operation
is required.

Purpose:
    - Provide async function-based interface for document processing
    - Enable non-blocking concurrent processing
    - Support integration with async frameworks (FastAPI, aiohttp, etc.)
    - Maximize throughput with async/await patterns

Target Users:
    - Async web frameworks (FastAPI, aiohttp)
    - Event-driven applications
    - High-throughput processing systems
    - Applications requiring non-blocking I/O

Usage Pattern:
    Use with async/await syntax in async contexts.
    All functions are coroutines that must be awaited.
"""

import asyncio
from typing import List, Optional, Dict, Any
from pathlib import Path

from ..orchestration_client import OrchestrationClient
from ..configuration.batch_configuration import BatchConfiguration


async def process_document_async(
    pdf_path: str,
    output_path: Optional[str] = None,
    output_filename: Optional[str] = None,
    max_retries: int = 3,
    **config_options
):
    """
    Process a single PDF document asynchronously.
    
    Async version of process_document. Processes document without
    blocking the event loop, suitable for integration with async
    frameworks and applications.
    
    Args:
        pdf_path: Path to PDF file to process
        output_path: Optional directory for output files
        output_filename: Optional custom output filename (no extension)
        max_retries: Maximum retry attempts on failure (default: 3)
        **config_options: Additional BatchConfiguration parameters
    
    Returns:
        DocumentResult object with processing outputs
    
    Raises:
        ProcessingError: If document processing fails
        ValidationError: If inputs are invalid
    
    Example:
        >>> # In async context
        >>> async def main():
        ...     result = await process_document_async("/data/document.pdf")
        ...     print(f"Output: {result.markdown_path}")
        >>> 
        >>> asyncio.run(main())
    """
    # Create configuration
    config = BatchConfiguration(
        max_retries_per_task=max_retries,
        enable_progress_reporting=config_options.get('show_progress', False),
        **{k: v for k, v in config_options.items() if k != 'show_progress'}
    )
    
    # Process in executor to avoid blocking
    loop = asyncio.get_event_loop()
    
    def _process():
        with OrchestrationClient(batch_config=config) as client:
            return client.orchestrate_single_document(
                pdf_path=pdf_path,
                output_path=output_path,
                output_filename=output_filename
            )
    
    result = await loop.run_in_executor(None, _process)
    return result


async def process_documents_async(
    pdf_paths: List[str],
    output_path: Optional[str] = None,
    max_concurrent: int = 5,
    max_retries: int = 3,
    show_progress: bool = False,
    **config_options
) -> List[Dict[str, Any]]:
    """
    Process multiple PDF documents asynchronously as a batch.
    
    Processes all documents concurrently without blocking, ideal for
    async frameworks and high-throughput scenarios.
    
    Args:
        pdf_paths: List of paths to PDF files
        output_path: Optional base directory for output files
        max_concurrent: Maximum concurrent tasks (default: 5)
        max_retries: Maximum retry attempts per document (default: 3)
        show_progress: Show progress bar (default: False for async)
        **config_options: Additional BatchConfiguration parameters
    
    Returns:
        List of dictionaries with processing results and status
    
    Example:
        >>> async def main():
        ...     paths = ["/data/doc1.pdf", "/data/doc2.pdf"]
        ...     results = await process_documents_async(
        ...         paths,
        ...         max_concurrent=10
        ...     )
        ...     
        ...     successful = [r for r in results if r['success']]
        ...     print(f"Processed {len(successful)}/{len(results)}")
        >>> 
        >>> asyncio.run(main())
    """
    # Create configuration
    config = BatchConfiguration(
        max_concurrent_tasks=max_concurrent,
        max_retries_per_task=max_retries,
        enable_progress_reporting=show_progress,
        **config_options
    )
    
    # Create client and process
    client = OrchestrationClient(batch_config=config)
    
    try:
        # Get processor pool initialized if needed
        if config.enable_processor_pooling:
            await client._get_processor_pool()
        
        # Process documents asynchronously
        tasks = client.batch_processor.create_tasks_from_paths(
            pdf_paths=pdf_paths,
            output_path=output_path
        )
        
        completed_tasks = await client.batch_processor.process_batch_async(tasks)
        
        # Convert to result dictionaries
        results = []
        for task in completed_tasks:
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
        
    finally:
        # Cleanup client resources
        client.cleanup()


async def process_directory_async(
    directory_path: str,
    file_pattern: str = "*.pdf",
    output_path: Optional[str] = None,
    max_concurrent: int = 5,
    max_retries: int = 3,
    show_progress: bool = False,
    **config_options
) -> Dict[str, Any]:
    """
    Process all PDF files in a directory asynchronously.
    
    Discovers and processes all matching PDF files without blocking,
    returning comprehensive summary.
    
    Args:
        directory_path: Path to directory containing PDF files
        file_pattern: Glob pattern for file matching (default: "*.pdf")
        output_path: Optional base directory for output files
        max_concurrent: Maximum concurrent tasks (default: 5)
        max_retries: Maximum retry attempts per document (default: 3)
        show_progress: Show progress bar (default: False for async)
        **config_options: Additional BatchConfiguration parameters
    
    Returns:
        Dictionary with comprehensive processing summary
    
    Example:
        >>> async def main():
        ...     summary = await process_directory_async(
        ...         "/data/pdfs/",
        ...         max_concurrent=10
        ...     )
        ...     print(f"Success rate: {summary['success_rate']:.1f}%")
        >>> 
        >>> asyncio.run(main())
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
    
    # Process all files asynchronously
    results = await process_documents_async(
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


async def process_concurrent_batches(
    batch_paths: List[List[str]],
    output_path: Optional[str] = None,
    max_concurrent_per_batch: int = 5,
    **config_options
) -> List[List[Dict[str, Any]]]:
    """
    Process multiple batches of documents concurrently.
    
    Advanced async pattern for processing multiple independent batches
    simultaneously. Each batch is processed internally with its own
    concurrency control.
    
    Args:
        batch_paths: List of batches, where each batch is a list of PDF paths
        output_path: Optional base directory for output files
        max_concurrent_per_batch: Max concurrent tasks within each batch
        **config_options: Additional BatchConfiguration parameters
    
    Returns:
        List of result lists, one for each input batch
    
    Example:
        >>> async def main():
        ...     # Process 3 batches concurrently
        ...     batch1 = ["/data/batch1/doc1.pdf", "/data/batch1/doc2.pdf"]
        ...     batch2 = ["/data/batch2/doc1.pdf", "/data/batch2/doc2.pdf"]
        ...     batch3 = ["/data/batch3/doc1.pdf", "/data/batch3/doc2.pdf"]
        ...     
        ...     results = await process_concurrent_batches(
        ...         [batch1, batch2, batch3],
        ...         max_concurrent_per_batch=3
        ...     )
        ...     
        ...     for i, batch_results in enumerate(results):
        ...         print(f"Batch {i+1}: {len(batch_results)} documents")
        >>> 
        >>> asyncio.run(main())
    """
    # Process all batches concurrently
    batch_tasks = [
        process_documents_async(
            pdf_paths=batch,
            output_path=output_path,
            max_concurrent=max_concurrent_per_batch,
            **config_options
        )
        for batch in batch_paths
    ]
    
    # Wait for all batches to complete
    results = await asyncio.gather(*batch_tasks, return_exceptions=False)
    
    return results

