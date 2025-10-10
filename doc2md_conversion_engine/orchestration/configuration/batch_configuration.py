#!/usr/bin/env python3
"""
Batch Processing Configuration Module

This module defines the BatchConfiguration dataclass which controls all aspects
of batch document processing operations including concurrency, retries, fault
tolerance, and performance optimization.

Purpose:
    - Centralize all batch processing settings
    - Provide sensible defaults for common scenarios
    - Enable validation of configuration parameters
    - Support different processing profiles (development, production, etc.)

Configuration Categories:
    1. Concurrency: Control parallel task execution
    2. Retry: Configure retry behavior and backoff strategies
    3. Performance: Optimize resource usage through pooling
    4. Fault Tolerance: Circuit breaker and error handling
    5. Monitoring: Progress reporting and logging levels
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class BatchConfiguration:
    """
    Configuration for batch document processing operations.
    
    This dataclass encapsulates all settings that control how multiple documents
    are processed concurrently, how failures are handled, and how resources are
    managed. It provides comprehensive control over the batch processing behavior.
    
    Concurrency Settings:
        max_concurrent_tasks: Maximum number of tasks processed simultaneously
        max_concurrent_processors: Maximum number of processor instances running
    
    Retry Configuration:
        enable_retries: Whether to retry failed tasks
        max_retries_per_task: Maximum retry attempts per task
        retry_delay_seconds: Base delay between retry attempts
        exponential_backoff: Use exponential backoff for retries
    
    Performance Optimization:
        enable_processor_pooling: Reuse processor instances (reduces overhead)
        processor_pool_size: Number of processors to keep in pool
        task_timeout_seconds: Maximum time allowed per task (None = no limit)
    
    Fault Tolerance:
        continue_on_error: Continue batch if individual tasks fail
        circuit_breaker_threshold: Failures before circuit breaker opens
        circuit_breaker_timeout: Seconds before circuit breaker resets
    
    Progress and Logging:
        enable_progress_reporting: Show progress bars during processing
        log_level: Logging verbosity (DEBUG, INFO, WARNING, ERROR)
    
    Example:
        >>> # Production configuration with high concurrency
        >>> prod_config = BatchConfiguration(
        ...     max_concurrent_tasks=10,
        ...     max_concurrent_processors=5,
        ...     enable_processor_pooling=True,
        ...     processor_pool_size=5,
        ...     max_retries_per_task=3,
        ...     exponential_backoff=True
        ... )
        
        >>> # Development configuration with verbose logging
        >>> dev_config = BatchConfiguration(
        ...     max_concurrent_tasks=2,
        ...     enable_progress_reporting=True,
        ...     log_level="DEBUG"
        ... )
    """
    
    # ========================================
    # Concurrency Settings
    # ========================================
    # Control how many tasks and processors run in parallel
    
    max_concurrent_tasks: int = 5
    """
    Maximum number of document processing tasks to run simultaneously.
    
    Higher values increase throughput but consume more system resources.
    Recommended: 2-3x CPU cores for I/O-bound tasks.
    """
    
    max_concurrent_processors: int = 3
    """
    Maximum number of processor instances that can run concurrently.
    
    Each processor handles one task at a time. Should be <= max_concurrent_tasks.
    Recommended: 1-2x CPU cores for CPU-bound processing.
    """
    
    # ========================================
    # Retry Configuration
    # ========================================
    # Control how failed tasks are retried
    
    enable_retries: bool = True
    """Whether to automatically retry failed processing tasks."""
    
    max_retries_per_task: int = 3
    """
    Maximum number of retry attempts for each failed task.
    
    Total attempts = 1 (initial) + max_retries_per_task
    Setting to 0 disables retries (initial attempt only).
    """
    
    retry_delay_seconds: float = 2.0
    """
    Base delay in seconds between retry attempts.
    
    With exponential_backoff enabled, actual delays are:
    - First retry: retry_delay_seconds
    - Second retry: retry_delay_seconds * 2
    - Third retry: retry_delay_seconds * 4
    - And so on (doubles each time)
    """
    
    exponential_backoff: bool = True
    """
    Use exponential backoff for retry delays.
    
    When True: Delay doubles after each retry (2s, 4s, 8s, ...)
    When False: Fixed delay between all retries (2s, 2s, 2s, ...)
    
    Exponential backoff is recommended to avoid overwhelming failing systems.
    """
    
    # ========================================
    # Performance Optimization
    # ========================================
    # Settings to improve throughput and resource usage
    
    enable_processor_pooling: bool = True
    """
    Reuse processor instances across multiple tasks.
    
    When True: Maintains a pool of initialized processors (faster, lower overhead)
    When False: Creates new processor for each task (slower, more isolated)
    
    Pooling is recommended for batch processing to reduce initialization overhead.
    """
    
    processor_pool_size: int = 3
    """
    Number of processor instances to maintain in the pool.
    
    Only used when enable_processor_pooling=True.
    Should be <= max_concurrent_processors for optimal resource usage.
    """
    
    task_timeout_seconds: Optional[float] = 600.0
    """
    Maximum time in seconds allowed for each task to complete.
    
    Tasks exceeding this timeout will be terminated and marked as failed.
    Set to None to disable timeout (not recommended for production).
    Default: 600 seconds (10 minutes)
    """
    
    # ========================================
    # Fault Tolerance
    # ========================================
    # Circuit breaker and error handling configuration
    
    continue_on_error: bool = True
    """
    Continue processing remaining tasks if some fail.
    
    When True: Failed tasks don't stop the batch (recommended for production)
    When False: First failure stops entire batch (useful for debugging)
    """
    
    circuit_breaker_threshold: int = 5
    """
    Number of consecutive failures before circuit breaker opens.
    
    When threshold is reached, all subsequent tasks are temporarily blocked
    to prevent cascading failures. Circuit resets after timeout period.
    """
    
    circuit_breaker_timeout: float = 60.0
    """
    Seconds to wait before attempting to close the circuit breaker.
    
    After this timeout, the circuit breaker will attempt to process tasks
    again to check if the underlying issue has been resolved.
    """
    
    # ========================================
    # Progress and Logging
    # ========================================
    # Control visibility into processing operations
    
    enable_progress_reporting: bool = True
    """
    Display progress bars during batch processing.
    
    Shows real-time progress of task completion. Disable for non-interactive
    environments or when output needs to be parseable.
    """
    
    log_level: str = "INFO"
    """
    Logging verbosity level.
    
    Options: "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    - DEBUG: Detailed information for diagnosing problems
    - INFO: Confirmation that things are working as expected
    - WARNING: Indication of potential problems
    - ERROR: Serious problems that prevented operations
    """
    
    def __post_init__(self) -> None:
        """
        Validate configuration parameters after initialization.
        
        This method is automatically called by the dataclass after __init__.
        It ensures all configuration values are valid and consistent.
        
        Raises:
            ValueError: If any configuration parameter is invalid
        
        Validation Rules:
            - All concurrency settings must be positive integers
            - max_concurrent_processors cannot exceed max_concurrent_tasks
            - processor_pool_size must be positive if pooling is enabled
        """
        # Import here to avoid circular dependency
        from ...exceptions import ConfigurationError
        
        # Validate concurrency settings
        if self.max_concurrent_tasks <= 0:
            raise ConfigurationError(
                "max_concurrent_tasks must be positive"
            )
        
        if self.max_concurrent_processors <= 0:
            raise ConfigurationError(
                "max_concurrent_processors must be positive"
            )
        
        # Validate processor pool size
        if self.processor_pool_size <= 0:
            raise ConfigurationError(
                "processor_pool_size must be positive"
            )
        
        # Ensure processor pool doesn't exceed concurrent limit
        if self.enable_processor_pooling:
            if self.processor_pool_size > self.max_concurrent_processors:
                # Auto-adjust pool size to match concurrent limit
                self.processor_pool_size = self.max_concurrent_processors


