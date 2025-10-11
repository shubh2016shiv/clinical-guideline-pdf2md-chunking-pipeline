#!/usr/bin/env python3
"""
Task Manager Module

This module handles the lifecycle of individual processing tasks, including
task execution, retry logic, timeout management, and state transitions.

Purpose:
    - Manage individual task execution from start to completion
    - Implement retry logic with configurable backoff
    - Handle task timeouts and cancellations
    - Track task state transitions
    - Coordinate with circuit breaker and processor pool

Task Lifecycle:
    1. Task created in PENDING state
    2. Task starts, transitions to PROCESSING
    3. On success: transitions to COMPLETED
    4. On failure: transitions to RETRYING (if retries available) or FAILED
    5. Final state: COMPLETED, FAILED, or SKIPPED
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from .models.processing_task import ProcessingTask
from .models.task_status import ProcessingStatus
from .resilience.circuit_breaker import CircuitBreaker
from .resilience.retry_handler import RetryHandler, RetryStrategy
from .resilience.resource_pool import ProcessorPool
from .configuration.batch_configuration import BatchConfiguration


class TaskManager:
    """
    Manages lifecycle and execution of individual processing tasks.
    
    Coordinates task execution with retry logic, timeout management,
    circuit breaker protection, and processor pool integration.
    
    Attributes:
        batch_config: Configuration for batch processing behavior
        circuit_breaker: Circuit breaker for fault protection
        processor_pool: Pool of processors (optional)
        retry_handler: Handler for retry logic
        logger: Logger instance
    
    Example:
        >>> manager = TaskManager(batch_config, circuit_breaker)
        >>> task = ProcessingTask(pdf_path="/data/doc.pdf")
        >>> completed_task = await manager.process_task_async(task)
    """
    
    def __init__(
        self,
        batch_config: BatchConfiguration,
        circuit_breaker: CircuitBreaker,
        processor_pool: Optional[ProcessorPool] = None
    ):
        """
        Initialize task manager.
        
        Args:
            batch_config: Batch processing configuration
            circuit_breaker: Circuit breaker for fault protection
            processor_pool: Optional processor pool for resource management
        """
        self.batch_config = batch_config
        self.circuit_breaker = circuit_breaker
        self.processor_pool = processor_pool
        self.processor = None  # Initialize processor attribute
        
        # Create retry handler from batch configuration
        self.retry_handler = RetryHandler(
            RetryStrategy(
                max_attempts=batch_config.max_retries_per_task + 1,  # +1 for initial
                base_delay=batch_config.retry_delay_seconds,
                use_exponential_backoff=batch_config.exponential_backoff
            )
        )
        
        self.logger = logging.getLogger(f"doc2md_conversion_engine.orchestration.task_manager.{self.__class__.__name__}")
    
    async def process_task_async(self, task: ProcessingTask) -> ProcessingTask:
        """
        Process a task asynchronously with retry logic.
        
        Main entry point for task processing. Handles the complete
        task lifecycle including retries, timeouts, and error handling.
        
        Args:
            task: ProcessingTask to execute
        
        Returns:
            Updated ProcessingTask with results or error information
        
        Process Flow:
            1. Check circuit breaker status
            2. Record task start time
            3. Attempt processing (with retries if configured)
            4. For each attempt:
               - Set status to PROCESSING
               - Execute with timeout if configured
               - On success: record result and return
               - On failure: check retry eligibility
               - If retryable: wait with backoff and retry
            5. If all retries exhausted: mark as FAILED
        """
        # Record start time
        task.started_at = time.time()
        
        # Attempt processing with retries
        for attempt in range(1, task.max_retries + 2):  # +1 for initial attempt
            task.attempts = attempt
            task.status = ProcessingStatus.PROCESSING
            
            try:
                # Execute task with optional timeout
                if self.batch_config.task_timeout_seconds:
                    result = await asyncio.wait_for(
                        self._execute_task(task),
                        timeout=self.batch_config.task_timeout_seconds
                    )
                else:
                    result = await self._execute_task(task)
                
                # Task succeeded
                task.result = result
                task.status = ProcessingStatus.COMPLETED
                task.completed_at = time.time()
                
                # Record success in circuit breaker
                self.circuit_breaker.record_success()
                
                return task
                
            except asyncio.TimeoutError:
                # Task timed out
                error_msg = f"Task timed out after {self.batch_config.task_timeout_seconds}s"
                self.logger.warning(f"{error_msg}: {task.pdf_path}")
                task.error = error_msg
                self.circuit_breaker.record_failure()
                
            except Exception as e:
                # Task failed with exception
                error_msg = str(e)
                self.logger.warning(
                    f"Processing attempt {attempt}/{task.max_retries + 1} failed "
                    f"for {Path(task.pdf_path).name}: {error_msg}"
                )
                task.error = error_msg
                self.circuit_breaker.record_failure()
            
            # Check if should retry
            if self.retry_handler.should_retry(attempt) and self.batch_config.enable_retries:
                task.status = ProcessingStatus.RETRYING
                
                # Wait before retry with backoff
                await self.retry_handler.sleep_before_retry_async(attempt)
                
                self.logger.info(
                    f"Retrying {Path(task.pdf_path).name} "
                    f"(attempt {attempt + 1}/{task.max_retries + 1})"
                )
        
        # All retries exhausted
        task.status = ProcessingStatus.FAILED
        task.completed_at = time.time()
        
        return task
    
    async def _execute_task(self, task: ProcessingTask):
        """
        Execute the actual processing operation for a task.
        
        Handles processor acquisition from pool (if available),
        actual document processing, and processor release.
        
        Args:
            task: ProcessingTask to execute
        
        Returns:
            DocumentResult from processing
        
        Raises:
            Exception: If processing fails
        """
        # Import here to avoid circular dependency
        from ..engine.document_processor import DocumentProcessor
        
        # Use processor pool if available
        if self.processor_pool and self.batch_config.enable_processor_pooling:
            processor = await self.processor_pool.acquire()
            try:
                # Process document using pooled processor
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    processor.convert_single_pdf_to_markdown,
                    task.pdf_path,
                    task.output_path,
                    task.output_filename
                )
                return result
            finally:
                # Always release processor back to pool
                await self.processor_pool.release(processor)
        else:
            # Use injected processor if available, otherwise create new one
            use_injected_processor = hasattr(self, 'processor') and self.processor is not None
            processor = self.processor if use_injected_processor else DocumentProcessor()
            
            # Log processor configuration
            self.logger.debug(f"Using {'injected' if use_injected_processor else 'new'} processor for async task")
            
            try:
                # Create a wrapper function to handle keyword arguments properly
                def process_doc_wrapper():
                    return processor.process_document(
                        pdf_path=task.pdf_path,
                        output_path=task.output_path,
                        output_filename=task.output_filename
                    )
                
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, process_doc_wrapper)
                return result
            finally:
                # Only cleanup processor if we created it (not injected)
                if not use_injected_processor:
                    processor.shutdown()
    
    def process_task_sync(self, task: ProcessingTask) -> ProcessingTask:
        """
        Process a task synchronously with retry logic.
        
        Synchronous version of process_task_async for use in
        thread pool executors or synchronous contexts.
        
        Args:
            task: ProcessingTask to execute
        
        Returns:
            Updated ProcessingTask with results or error information
        """
        # Import here to avoid circular dependency
        from ..engine.document_processor import DocumentProcessor
        
        task.started_at = time.time()
        
        # Use injected processor if available, otherwise create new one
        use_injected_processor = hasattr(self, 'processor') and self.processor is not None
        processor = self.processor if use_injected_processor else DocumentProcessor()
        
        # Log processor configuration
        self.logger.info(f"Using {'injected' if use_injected_processor else 'new'} processor for sync task")
        
        try:
            # Attempt processing with retries
            for attempt in range(1, task.max_retries + 2):  # +1 for initial
                task.attempts = attempt
                task.status = ProcessingStatus.PROCESSING
                
                try:
                    result = processor.process_document(
                        pdf_path=task.pdf_path,
                        output_path=task.output_path,
                        output_filename=task.output_filename
                    )
                    
                    # Task succeeded
                    task.result = result
                    task.status = ProcessingStatus.COMPLETED
                    task.completed_at = time.time()
                    self.circuit_breaker.record_success()
                    
                    return task
                        
                except Exception as e:
                    # Task failed
                    error_msg = str(e)
                    self.logger.warning(
                        f"Processing attempt {attempt}/{task.max_retries + 1} failed "
                        f"for {Path(task.pdf_path).name}: {error_msg}"
                    )
                    task.error = error_msg
                    self.circuit_breaker.record_failure()
                    
                    # Check if should retry
                    if self.retry_handler.should_retry(attempt) and self.batch_config.enable_retries:
                        task.status = ProcessingStatus.RETRYING
                        self.retry_handler.sleep_before_retry(attempt)
            
            # All retries exhausted
            task.status = ProcessingStatus.FAILED
            task.completed_at = time.time()
            
            return task
        finally:
            # Only shutdown processor if we created it (not injected)
            if not use_injected_processor:
                processor.shutdown()




