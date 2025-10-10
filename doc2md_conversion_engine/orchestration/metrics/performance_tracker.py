#!/usr/bin/env python3
"""
Performance Tracker Module

This module provides comprehensive metrics collection and reporting for
document processing operations. It tracks success rates, processing times,
resource usage, and other performance indicators.

Purpose:
    - Collect processing metrics in real-time
    - Calculate aggregated statistics across batches
    - Generate comprehensive performance reports
    - Support monitoring and alerting systems
    - Enable performance optimization decisions

Metrics Categories:
    1. Throughput: Tasks processed per unit time
    2. Success Rate: Ratio of successful vs failed tasks
    3. Timing: Processing durations and averages
    4. Retry Behavior: Retry attempts and patterns
    5. Resource Extraction: Figures, tables, etc.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import time


@dataclass
class PerformanceMetrics:
    """
    Container for performance metrics data.
    
    Holds all performance-related metrics collected during processing
    operations. Metrics are updated incrementally as tasks complete.
    
    Attributes:
        total_tasks: Total number of tasks processed
        completed_tasks: Number of successfully completed tasks
        failed_tasks: Number of failed tasks
        retried_tasks: Number of tasks that required retries
        total_processing_time: Sum of all task processing times (seconds)
        start_time: Timestamp when metrics collection started
    """
    
    total_tasks: int = 0
    """Total number of tasks processed (includes successful and failed)."""
    
    completed_tasks: int = 0
    """Number of tasks completed successfully."""
    
    failed_tasks: int = 0
    """Number of tasks that failed (after all retries exhausted)."""
    
    retried_tasks: int = 0
    """Number of tasks that required at least one retry."""
    
    total_processing_time: float = 0.0
    """Cumulative processing time across all tasks (seconds)."""
    
    start_time: float = field(default_factory=time.time)
    """Unix timestamp when metrics collection began."""
    
    def reset(self) -> None:
        """
        Reset all metrics to initial values.
        
        Useful for starting a new measurement period or after
        generating a report.
        """
        self.total_tasks = 0
        self.completed_tasks = 0
        self.failed_tasks = 0
        self.retried_tasks = 0
        self.total_processing_time = 0.0
        self.start_time = time.time()


class PerformanceTracker:
    """
    Tracks and reports performance metrics for document processing.
    
    Collects metrics incrementally as tasks complete and provides
    methods to calculate derived statistics and generate reports.
    
    The tracker maintains running totals and can compute aggregated
    statistics like success rates, average processing times, and
    throughput metrics.
    
    Attributes:
        metrics: PerformanceMetrics object holding raw metric data
    
    Example:
        >>> tracker = PerformanceTracker()
        >>> 
        >>> # Update metrics as tasks complete
        >>> tracker.record_task_completion(success=True, duration=5.2)
        >>> tracker.record_task_completion(success=False, duration=3.1)
        >>> 
        >>> # Get summary statistics
        >>> summary = tracker.get_summary()
        >>> print(f"Success rate: {summary['success_rate']:.1f}%")
    """
    
    def __init__(self):
        """Initialize performance tracker with empty metrics."""
        self.metrics = PerformanceMetrics()
    
    def record_task_completion(
        self,
        success: bool,
        duration: Optional[float] = None,
        was_retried: bool = False
    ) -> None:
        """
        Record completion of a processing task.
        
        Updates relevant metrics based on whether the task succeeded
        or failed, and optionally records processing duration.
        
        Args:
            success: True if task completed successfully, False if failed
            duration: Processing duration in seconds (optional)
            was_retried: True if task required retry attempts
        
        Side Effects:
            - Increments total_tasks counter
            - Increments completed_tasks (success) or failed_tasks (failure)
            - Increments retried_tasks if was_retried is True
            - Adds duration to total_processing_time if provided
        
        Example:
            >>> tracker = PerformanceTracker()
            >>> 
            >>> # Successful task
            >>> tracker.record_task_completion(
            ...     success=True,
            ...     duration=5.2,
            ...     was_retried=False
            ... )
            >>> 
            >>> # Failed task that was retried
            >>> tracker.record_task_completion(
            ...     success=False,
            ...     duration=8.5,
            ...     was_retried=True
            ... )
        """
        # Increment total tasks counter
        self.metrics.total_tasks += 1
        
        # Update success/failure counters
        if success:
            self.metrics.completed_tasks += 1
        else:
            self.metrics.failed_tasks += 1
        
        # Track retry attempts
        if was_retried:
            self.metrics.retried_tasks += 1
        
        # Add processing duration if provided
        if duration is not None:
            self.metrics.total_processing_time += duration
    
    def calculate_success_rate(self) -> float:
        """
        Calculate success rate as a percentage.
        
        Computes the ratio of successful tasks to total tasks,
        returned as a percentage (0-100).
        
        Returns:
            Success rate percentage (0.0 if no tasks processed)
        
        Example:
            >>> tracker = PerformanceTracker()
            >>> tracker.record_task_completion(success=True)
            >>> tracker.record_task_completion(success=True)
            >>> tracker.record_task_completion(success=False)
            >>> tracker.calculate_success_rate()
            66.67
        """
        if self.metrics.total_tasks == 0:
            return 0.0
        
        return (self.metrics.completed_tasks / self.metrics.total_tasks) * 100
    
    def calculate_average_processing_time(self) -> float:
        """
        Calculate average processing time per task.
        
        Computes the mean processing duration across all tasks
        that provided duration information.
        
        Returns:
            Average processing time in seconds (0.0 if no durations recorded)
        
        Example:
            >>> tracker = PerformanceTracker()
            >>> tracker.record_task_completion(success=True, duration=5.0)
            >>> tracker.record_task_completion(success=True, duration=7.0)
            >>> tracker.calculate_average_processing_time()
            6.0
        """
        if self.metrics.completed_tasks == 0:
            return 0.0
        
        return self.metrics.total_processing_time / self.metrics.completed_tasks
    
    def calculate_throughput(self) -> float:
        """
        Calculate processing throughput (tasks per second).
        
        Computes how many tasks are processed per second based on
        elapsed time since metrics collection started.
        
        Returns:
            Tasks per second (0.0 if < 1 second elapsed)
        
        Example:
            >>> tracker = PerformanceTracker()
            >>> # Process 10 tasks over 5 seconds
            >>> time.sleep(5)
            >>> for _ in range(10):
            ...     tracker.record_task_completion(success=True)
            >>> tracker.calculate_throughput()
            2.0  # 10 tasks / 5 seconds = 2 tasks/second
        """
        elapsed_time = time.time() - self.metrics.start_time
        
        if elapsed_time < 1.0:
            return 0.0
        
        return self.metrics.total_tasks / elapsed_time
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Generate comprehensive performance summary.
        
        Creates a dictionary containing all raw metrics plus
        calculated derived statistics like success rate,
        average times, and throughput.
        
        Returns:
            Dictionary with all performance metrics and statistics
        
        Example:
            >>> tracker = PerformanceTracker()
            >>> # ... process tasks ...
            >>> summary = tracker.get_summary()
            >>> print(summary)
            {
                'total_tasks': 100,
                'completed_tasks': 95,
                'failed_tasks': 5,
                'success_rate': 95.0,
                'average_processing_time': 4.2,
                'throughput': 2.5,
                ...
            }
        """
        return {
            # Raw counters
            "total_tasks": self.metrics.total_tasks,
            "completed_tasks": self.metrics.completed_tasks,
            "failed_tasks": self.metrics.failed_tasks,
            "retried_tasks": self.metrics.retried_tasks,
            
            # Derived statistics
            "success_rate": self.calculate_success_rate(),
            "average_processing_time": self.calculate_average_processing_time(),
            "total_processing_time": self.metrics.total_processing_time,
            "throughput_tasks_per_second": self.calculate_throughput(),
            
            # Timing information
            "elapsed_time": time.time() - self.metrics.start_time,
            "start_time": self.metrics.start_time,
        }
    
    def generate_task_summary(self, tasks: List) -> Dict[str, Any]:
        """
        Generate summary from a list of ProcessingTask objects.
        
        Analyzes completed tasks to extract comprehensive statistics
        including success rates, timing information, and resource
        extraction counts (figures, tables).
        
        Args:
            tasks: List of ProcessingTask objects to analyze
        
        Returns:
            Dictionary with comprehensive task statistics
        
        Example:
            >>> tracker = PerformanceTracker()
            >>> summary = tracker.generate_task_summary(completed_tasks)
            >>> print(f"Success rate: {summary['success_rate']:.1f}%")
            >>> print(f"Total figures: {summary['total_figures_extracted']}")
        """
        if not tasks:
            return {
                "total_tasks": 0,
                "successful": 0,
                "failed": 0,
                "success_rate": 0.0
            }
        
        # Import here to avoid circular dependency
        from ..models.task_status import ProcessingStatus
        
        # Separate successful and failed tasks
        successful_tasks = [
            t for t in tasks
            if t.status == ProcessingStatus.COMPLETED
        ]
        failed_tasks = [
            t for t in tasks
            if t.status == ProcessingStatus.FAILED
        ]
        
        # Extract timing information from tasks with durations
        durations = [t.duration for t in tasks if t.duration is not None]
        
        # Count extracted resources (figures, tables) from successful tasks
        total_figures = sum(
            len(t.result.figures) for t in successful_tasks
            if t.result and hasattr(t.result, 'figures')
        )
        total_tables = sum(
            len(t.result.tables) for t in successful_tasks
            if t.result and hasattr(t.result, 'tables')
        )
        
        # Build comprehensive summary
        summary = {
            # Task counts
            "total_tasks": len(tasks),
            "successful": len(successful_tasks),
            "failed": len(failed_tasks),
            "success_rate": (len(successful_tasks) / len(tasks)) * 100,
            
            # Retry statistics
            "total_retries": sum(t.attempts - 1 for t in tasks),
            "tasks_requiring_retry": sum(1 for t in tasks if t.attempts > 1),
            
            # Resource extraction counts
            "total_figures_extracted": total_figures,
            "total_tables_extracted": total_tables,
            
            # Timing statistics
            "total_processing_time": sum(durations),
            "average_processing_time": sum(durations) / len(durations) if durations else 0.0,
            "min_processing_time": min(durations) if durations else 0.0,
            "max_processing_time": max(durations) if durations else 0.0,
            
            # Failed task details for debugging
            "failed_documents": [
                {
                    "path": t.pdf_path,
                    "error": t.error,
                    "attempts": t.attempts
                }
                for t in failed_tasks
            ]
        }
        
        return summary
    
    def reset(self) -> None:
        """
        Reset all metrics to start fresh measurement period.
        
        Clears all counters and timers, useful for measuring
        performance of specific batches or time periods.
        """
        self.metrics.reset()




