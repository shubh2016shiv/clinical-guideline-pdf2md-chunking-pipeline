#!/usr/bin/env python3
"""
Processing Task Model Module

This module defines the ProcessingTask dataclass which represents a single
document processing task within the orchestration system.

Purpose:
    - Encapsulates all information about a processing task
    - Tracks task lifecycle: creation, start, completion
    - Records success/failure status and error information
    - Manages retry attempts and configuration

The ProcessingTask serves as the primary unit of work in batch processing
operations, carrying all necessary context from creation through completion.
"""

import time
from dataclasses import dataclass, field
from typing import Optional

from .task_status import ProcessingStatus


@dataclass
class ProcessingTask:
    """
    Represents a single document processing task with full lifecycle tracking.
    
    This dataclass contains all information needed to process a document,
    track its progress, handle failures, and record results. Each task
    maintains its own state, timing information, and result/error data.
    
    Attributes:
        pdf_path: Path to the PDF file to process
        output_path: Optional custom output directory for results
        output_filename: Optional custom filename for output (without extension)
        status: Current processing status (default: PENDING)
        result: DocumentResult object if processing succeeded, None otherwise
        error: Error message string if processing failed, None otherwise
        attempts: Number of processing attempts made (includes initial + retries)
        max_retries: Maximum number of retry attempts allowed for this task
        created_at: Unix timestamp when task was created
        started_at: Unix timestamp when processing began, None if not started
        completed_at: Unix timestamp when processing finished, None if not finished
    
    Properties:
        duration: Calculated processing duration in seconds (None if not finished)
        can_retry: Boolean indicating if task is eligible for retry
    
    Example:
        >>> task = ProcessingTask(
        ...     pdf_path="/data/document.pdf",
        ...     max_retries=3
        ... )
        >>> task.status = ProcessingStatus.PROCESSING
        >>> task.started_at = time.time()
        >>> # ... processing occurs ...
        >>> task.status = ProcessingStatus.COMPLETED
        >>> task.completed_at = time.time()
        >>> print(f"Processed in {task.duration:.2f} seconds")
    """
    
    # Input parameters - set at task creation
    pdf_path: str
    """Absolute or relative path to the PDF document to process."""
    
    output_path: Optional[str] = None
    """Optional custom directory where processing outputs will be saved."""
    
    output_filename: Optional[str] = None
    """Optional custom filename for output (without extension), defaults to PDF stem."""
    
    # State tracking - modified during task lifecycle
    status: ProcessingStatus = ProcessingStatus.PENDING
    """Current status of the task in its processing lifecycle."""
    
    result: Optional[any] = None  # Type hint: Optional[DocumentResult]
    """DocumentResult object containing processing outputs, None until completion."""
    
    error: Optional[str] = None
    """Human-readable error message if processing failed, None on success."""
    
    # Retry management
    attempts: int = 0
    """Number of processing attempts made (0 initially, incremented before each attempt)."""
    
    max_retries: int = 3
    """Maximum number of retry attempts allowed after initial failure."""
    
    # Timing information - timestamps for lifecycle events
    created_at: float = field(default_factory=time.time)
    """Unix timestamp (seconds) when this task was created."""
    
    started_at: Optional[float] = None
    """Unix timestamp (seconds) when processing started, None if not yet started."""
    
    completed_at: Optional[float] = None
    """Unix timestamp (seconds) when processing finished, None if still running."""
    
    @property
    def duration(self) -> Optional[float]:
        """
        Calculate total processing duration in seconds.
        
        Computes the elapsed time between when processing started and when it
        completed. This includes all retry attempts but excludes retry delays.
        
        Returns:
            Float representing duration in seconds, or None if task hasn't
            started or hasn't completed yet.
        
        Example:
            >>> if task.duration:
            ...     print(f"Task took {task.duration:.2f}s")
        """
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None
    
    @property
    def can_retry(self) -> bool:
        """
        Check if this task is eligible for retry.
        
        A task can be retried if:
        1. It is currently in FAILED status
        2. It has not exhausted its maximum retry attempts
        
        Returns:
            True if task can be retried, False otherwise
        
        Example:
            >>> if task.can_retry:
            ...     retry_handler.schedule_retry(task)
        """
        return self.attempts < self.max_retries and self.status == ProcessingStatus.FAILED


