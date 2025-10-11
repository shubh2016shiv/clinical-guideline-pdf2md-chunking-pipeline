#!/usr/bin/env python3
"""
Document Processing Entry Point

This module provides the main entry point for processing clinical guideline
documents. It generates unique request IDs, orchestrates the processing
pipeline, and provides progress tracking and comprehensive result summaries.

Purpose:
    - Serve as the primary interface to the document processing engine
    - Generate unique request IDs for traceability and logging
    - Provide simple function calls for single/batch processing
    - Track and report processing progress and results

Functions:
    - process_single_document: Process one PDF file
    - process_document_batch: Process multiple PDF files
    - process_documents_from_directory: Process all PDFs in a directory

Usage:
    from process_documents import process_single_document
    
    result = process_single_document(
        pdf_file_path="/data/clinical_guideline.pdf",
        output_directory="/output"
    )
"""

import logging
import time
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional

from doc2md_conversion_engine.orchestration import (
    convert_single_pdf_to_markdown,
    convert_pdf_batch_to_markdown,
    convert_directory_pdfs_to_markdown
)
from doc2md_conversion_engine.exceptions import ProcessingError, ValidationError


# Configure logging for this module
logger = logging.getLogger(__name__)


def start_single_doc_processing(
    pdf_file_path: str,
    output_directory: Optional[str] = None,
    max_retry_attempts: int = 3,
    gemini_api_key: Optional[str] = None,
    enable_gemini: bool = False
) -> Dict[str, Any]:
    """
    Process a single PDF document with tracking and error handling.
    
    Creates a unique request ID, processes the document through the
    orchestration engine, and returns comprehensive results including
    processing metadata.
    
    Args:
        pdf_file_path: Full path to the PDF file to process
        output_directory: Directory where outputs will be saved (optional)
        max_retry_attempts: Maximum number of retry attempts on failure
        gemini_api_key: Google Gemini API key for figure summarization (optional)
        enable_gemini: Whether to enable Gemini AI for figure summarization (default: False)
    
    Returns:
        Dictionary containing:
            - request_id: Unique identifier for this processing request
            - success: Boolean indicating if processing succeeded
            - pdf_path: Path to the input PDF file
            - markdown_path: Path to generated markdown (if successful)
            - figures_extracted: Count of figures extracted (if successful)
            - tables_extracted: Count of tables extracted (if successful)
            - processing_duration_seconds: Time taken to process
            - error_message: Error details (if failed)
    
    Raises:
        ValidationError: If PDF file path is invalid
        ProcessingError: If processing fails after all retries
    
    Example:
        >>> result = start_single_doc_processing(
        ...     pdf_file_path="/data/MASH_guideline.pdf",
        ...     output_directory="/output/processed"
        ... )
        >>> print(f"Request ID: {result['request_id']}")
        >>> print(f"Success: {result['success']}")
    """
    # Generate unique request ID for traceability
    request_id = str(uuid.uuid4())

    # TODO: // Do not assume the input is only PDF - allow for other file types that docling supports
    # Validate input file exists
    pdf_path = Path(pdf_file_path)
    if not pdf_path.exists():
        raise ValidationError(f"PDF file not found: {pdf_file_path}")
    
    if not pdf_path.is_file():
        raise ValidationError(f"Path is not a file: {pdf_file_path}")
    
    logger.info(f"Request {request_id}: Processing document '{pdf_path.name}'")
    
    # Track processing start time
    start_time = time.time()
    
    try:
        # Process document through orchestration engine with Gemini config
        document_result = convert_single_pdf_to_markdown(
            pdf_path=str(pdf_file_path),
            output_path=output_directory,
            max_retries=max_retry_attempts,
            gemini_api_key=gemini_api_key,
            enable_gemini=enable_gemini
        )
        
        # Calculate processing duration
        processing_duration = time.time() - start_time
        
        # Build success result dictionary
        result = {
            'request_id': request_id,
            'success': True,
            'pdf_path': str(pdf_file_path),
            'markdown_path': document_result.markdown_path,
            'figures_extracted': len(document_result.figures),
            'tables_extracted': len(document_result.tables),
            'processing_duration_seconds': round(processing_duration, 2),
            'error_message': None
        }
        
        logger.info(
            f"Request {request_id}: Completed successfully in {processing_duration:.2f}s "
            f"({result['figures_extracted']} figures, {result['tables_extracted']} tables)"
        )
        
        return result
        
    except Exception as error:
        # Calculate processing duration even on failure
        processing_duration = time.time() - start_time
        
        # Extract clean error message for user-facing output
        if hasattr(error, 'message'):
            # For our custom exceptions, use the clean message
            clean_error_message = error.message
        else:
            # For other exceptions, use the string representation
            clean_error_message = str(error)
        
        # Build failure result dictionary
        result = {
            'request_id': request_id,
            'success': False,
            'pdf_path': str(pdf_file_path),
            'markdown_path': None,
            'figures_extracted': 0,
            'tables_extracted': 0,
            'processing_duration_seconds': round(processing_duration, 2),
            'error_message': clean_error_message
        }
        
        logger.error(f"Request {request_id}: Failed - {clean_error_message}")
        
        # Re-raise the original error without wrapping to avoid nested messages
        raise error


def start_batch_doc_processing(
    pdf_file_paths: List[str],
    output_directory: Optional[str] = None,
    max_concurrent_tasks: int = 5,
    max_retry_attempts: int = 3,
    show_progress_bar: bool = True
) -> Dict[str, Any]:
    """
    Process multiple PDF documents as a batch with progress tracking.
    
    Creates a unique request ID for the batch, processes all documents
    concurrently with configured parallelism, and returns comprehensive
    summary of results.
    
    Args:
        pdf_file_paths: List of paths to PDF files to process
        output_directory: Base directory for all outputs (optional)
        max_concurrent_tasks: Maximum documents to process simultaneously
        max_retry_attempts: Maximum retry attempts per document
        show_progress_bar: Whether to display progress bar during processing
    
    Returns:
        Dictionary containing:
            - request_id: Unique identifier for this batch request
            - total_documents: Total number of documents in batch
            - successful_count: Number of successfully processed documents
            - failed_count: Number of failed documents
            - success_rate_percentage: Percentage of successful processings
            - total_duration_seconds: Total time for entire batch
            - individual_results: List of per-document result dictionaries
            - failed_documents: List of failed document paths with errors
    
    Example:
        >>> pdf_files = [
        ...     "/data/guideline1.pdf",
        ...     "/data/guideline2.pdf",
        ...     "/data/guideline3.pdf"
        ... ]
        >>> summary = start_batch_doc_processing(
        ...     pdf_file_paths=pdf_files,
        ...     max_concurrent_tasks=3
        ... )
        >>> print(f"Processed {summary['successful_count']}/{summary['total_documents']}")
    """
    # Generate unique request ID for this batch
    batch_request_id = str(uuid.uuid4())
    
    logger.info(
        f"Batch Request {batch_request_id}: Processing {len(pdf_file_paths)} documents "
        f"(max concurrent: {max_concurrent_tasks})"
    )
    
    # Track batch processing start time
    batch_start_time = time.time()
    
    # Process all documents through orchestration engine
    processing_results = convert_pdf_batch_to_markdown(
        pdf_paths=pdf_file_paths,
        output_path=output_directory,
        max_concurrent=max_concurrent_tasks,
        max_retries=max_retry_attempts,
        show_progress=show_progress_bar
    )
    
    # Calculate batch processing duration
    batch_duration = time.time() - batch_start_time
    
    # Count successful and failed documents
    successful_count = sum(1 for result in processing_results if result['success'])
    failed_count = len(processing_results) - successful_count
    
    # Calculate success rate percentage
    success_rate = (successful_count / len(processing_results) * 100) if processing_results else 0.0
    
    # Extract failed document information
    failed_documents = [
        {
            'pdf_path': result['pdf_path'],
            'error_message': result['error']
        }
        for result in processing_results
        if not result['success']
    ]
    
    # Build comprehensive batch summary
    batch_summary = {
        'request_id': batch_request_id,
        'total_documents': len(processing_results),
        'successful_count': successful_count,
        'failed_count': failed_count,
        'success_rate_percentage': round(success_rate, 2),
        'total_duration_seconds': round(batch_duration, 2),
        'individual_results': processing_results,
        'failed_documents': failed_documents
    }
    
    logger.info(
        f"Batch Request {batch_request_id}: Completed in {batch_duration:.2f}s - "
        f"{successful_count}/{len(processing_results)} successful ({success_rate:.1f}%)"
    )
    
    if failed_documents:
        logger.warning(f"Batch Request {batch_request_id}: {failed_count} documents failed")
    
    return batch_summary


def start_docs_processing_from_directory(
    directory_path: str,
    file_pattern: str = "*.pdf",
    output_directory: Optional[str] = None,
    max_concurrent_tasks: int = 5,
    max_retry_attempts: int = 3,
    show_progress_bar: bool = True
) -> Dict[str, Any]:
    """
    Process all PDF files found in a directory with progress tracking.
    
    Discovers all PDF files matching the pattern, creates a unique request ID,
    and processes all documents as a batch with comprehensive reporting.
    
    Args:
        directory_path: Path to directory containing PDF files
        file_pattern: Glob pattern for matching files (default: "*.pdf")
        output_directory: Base directory for all outputs (optional)
        max_concurrent_tasks: Maximum documents to process simultaneously
        max_retry_attempts: Maximum retry attempts per document
        show_progress_bar: Whether to display progress bar during processing
    
    Returns:
        Dictionary containing:
            - request_id: Unique identifier for this directory processing request
            - source_directory: Path to the source directory
            - files_found: Number of PDF files discovered
            - total_documents: Total number of documents processed
            - successful_count: Number of successfully processed documents
            - failed_count: Number of failed documents
            - success_rate_percentage: Percentage of successful processings
            - total_duration_seconds: Total time for entire operation
            - individual_results: List of per-document result dictionaries
            - failed_documents: List of failed document paths with errors
    
    Raises:
        ValidationError: If directory path is invalid
    
    Example:
        >>> summary = start_docs_processing_from_directory(
        ...     directory_path="/data/clinical_guidelines",
        ...     max_concurrent_tasks=10
        ... )
        >>> print(f"Processed {summary['files_found']} PDFs from directory")
        >>> print(f"Success rate: {summary['success_rate_percentage']}%")
    """
    # Generate unique request ID
    directory_request_id = str(uuid.uuid4())
    
    # Validate directory exists
    source_directory = Path(directory_path)
    if not source_directory.exists():
        raise ValidationError(f"Directory not found: {directory_path}")
    
    if not source_directory.is_dir():
        raise ValidationError(f"Path is not a directory: {directory_path}")
    
    logger.info(
        f"Directory Request {directory_request_id}: "
        f"Processing all '{file_pattern}' files from '{directory_path}'"
    )
    
    # Track operation start time
    operation_start_time = time.time()
    
    # Process directory through orchestration engine
    directory_summary = convert_directory_pdfs_to_markdown(
        directory_path=directory_path,
        file_pattern=file_pattern,
        output_path=output_directory,
        max_concurrent=max_concurrent_tasks,
        max_retries=max_retry_attempts,
        show_progress=show_progress_bar
    )
    
    # Calculate total operation duration
    operation_duration = time.time() - operation_start_time
    
    # Enhance summary with request ID and timing
    enhanced_summary = {
        'request_id': directory_request_id,
        'source_directory': str(directory_path),
        'files_found': directory_summary['total_files'],
        'total_documents': directory_summary['total_files'],
        'successful_count': directory_summary['successful'],
        'failed_count': directory_summary['failed'],
        'success_rate_percentage': round(directory_summary['success_rate'], 2),
        'total_duration_seconds': round(operation_duration, 2),
        'individual_results': directory_summary['results'],
        'failed_documents': directory_summary['failed_files']
    }
    
    logger.info(
        f"Directory Request {directory_request_id}: Completed in {operation_duration:.2f}s - "
        f"{enhanced_summary['successful_count']}/{enhanced_summary['files_found']} successful "
        f"({enhanced_summary['success_rate_percentage']}%)"
    )
    
    if enhanced_summary['failed_documents']:
        logger.warning(
            f"Directory Request {directory_request_id}: "
            f"{enhanced_summary['failed_count']} documents failed"
        )
    
    return enhanced_summary

