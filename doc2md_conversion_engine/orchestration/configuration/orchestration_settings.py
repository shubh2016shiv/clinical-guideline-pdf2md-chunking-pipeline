#!/usr/bin/env python3
"""
Orchestration Settings Module

This module provides additional orchestration-level configuration settings
that complement the batch configuration. These settings control global
orchestration behavior, metrics collection, and system-wide defaults.

Purpose:
    - Define system-wide orchestration parameters
    - Provide defaults for common orchestration scenarios
    - Enable configuration of metrics and monitoring
    - Support feature toggles for experimental features
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class OrchestrationSettings:
    """
    System-wide settings for the orchestration framework.
    
    These settings apply globally to the orchestration system and affect
    how the orchestrator coordinates tasks, collects metrics, and manages
    system resources.
    
    Attributes:
        enable_metrics_collection: Collect detailed performance metrics
        metrics_aggregation_interval: Seconds between metric aggregations
        default_output_directory: Base directory for all processing outputs
        cleanup_on_shutdown: Clean up resources when orchestrator shuts down
        enable_detailed_logging: Include detailed debug information in logs
        max_queue_size: Maximum number of tasks that can be queued
    
    Example:
        >>> settings = OrchestrationSettings(
        ...     enable_metrics_collection=True,
        ...     default_output_directory="/data/processed",
        ...     cleanup_on_shutdown=True
        ... )
    """
    
    # ========================================
    # Metrics and Monitoring
    # ========================================
    
    enable_metrics_collection: bool = True
    """
    Enable collection of detailed performance metrics.
    
    When enabled, the orchestrator tracks processing times, success rates,
    resource usage, and other performance indicators. Metrics can be
    retrieved via get_metrics() method.
    """
    
    metrics_aggregation_interval: float = 60.0
    """
    Interval in seconds for aggregating collected metrics.
    
    Metrics are periodically summarized and can be exported or logged.
    Lower values provide more real-time data but increase overhead.
    """
    
    # ========================================
    # Resource Management
    # ========================================
    
    default_output_directory: Optional[str] = None
    """
    Default base directory for processing outputs.
    
    If specified, all processed documents will be saved under this directory
    unless overridden at the task level. If None, uses current directory.
    """
    
    cleanup_on_shutdown: bool = True
    """
    Automatically clean up resources when orchestrator shuts down.
    
    When True, processor pools and other resources are properly released.
    Should always be True in production to prevent resource leaks.
    """
    
    max_queue_size: Optional[int] = None
    """
    Maximum number of tasks that can be queued for processing.
    
    Prevents memory issues when processing very large batches.
    If None, queue size is unlimited (not recommended for production).
    Recommended: 1000-10000 depending on available memory.
    """
    
    # ========================================
    # Logging and Debugging
    # ========================================
    
    enable_detailed_logging: bool = False
    """
    Include detailed debug information in log messages.
    
    When enabled, logs include stack traces, variable states, and timing
    information. Useful for debugging but increases log volume significantly.
    """
    
    log_task_parameters: bool = False
    """
    Log full task parameters and configuration for each task.
    
    Useful for auditing and debugging but may expose sensitive paths or
    configuration details. Use with caution in production.
    """
    
    # ========================================
    # Experimental Features
    # ========================================
    
    enable_adaptive_concurrency: bool = False
    """
    Automatically adjust concurrency based on system load.
    
    EXPERIMENTAL: When enabled, the orchestrator monitors system resources
    and dynamically adjusts the number of concurrent tasks to optimize
    performance. May cause unpredictable behavior.
    """
    
    def __post_init__(self) -> None:
        """
        Validate settings after initialization.
        
        Ensures all configuration values are valid and consistent.
        
        Raises:
            ValueError: If any setting is invalid
        """
        if self.metrics_aggregation_interval <= 0:
            raise ValueError("metrics_aggregation_interval must be positive")
        
        if self.max_queue_size is not None and self.max_queue_size <= 0:
            raise ValueError("max_queue_size must be positive if specified")


