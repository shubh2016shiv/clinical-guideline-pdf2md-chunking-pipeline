#!/usr/bin/env python3
"""
Batch Processor Module

This module coordinates batch processing of multiple documents with
concurrency control, progress tracking, and comprehensive error handling.

Purpose:
    - Coordinate parallel processing of multiple documents
    - Manage concurrency with semaphores for resource control
    - Track progress across the batch
    - Collect and aggregate results
    - Handle batch-level errors gracefully

Processing Modes:
    1. Asynchronous: Maximum concurrency with async/await
    2. Synchronous: Thread pool based parallelism

The batch processor delegates individual task execution to TaskManager
while handling batch-level concerns like concurrency limits, progress
reporting, and result aggregation.
"""

import asyncio
import logging
from pathlib import Path
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models.processing_task import ProcessingTask
from .models.task_status import ProcessingStatus
from .task_manager import TaskManager
from .configuration.batch_configuration import BatchConfiguration
from ..utils.progress import ProgressManager


class BatchProcessor:
    """
    Coordinates batch processing of multiple documents.
    
    Manages concurrent execution of multiple tasks with progress tracking,
    error handling, and result aggregation. Works with TaskManager to
    execute individual tasks while handling batch-level coordination.
    
    Attributes:
        batch_config: Configuration for batch processing
        task_manager: Manager for individual task execution
        progress_manager: Manager for progress reporting
        logger: Logger instance
    
    Example:
        >>> processor = BatchProcessor(batch_config, task_manager)
        >>> tasks = [ProcessingTask(pdf_path=p) for p in pdf_paths]
        >>> results = await processor.process_batch_async(tasks)
    """
    
    def __init__(
        self,
        batch_config: BatchConfiguration,
        task_manager: TaskManager,
        progress_manager: Optional[ProgressManager] = None
    ):
        """
        Initialize batch processor.
        
        Args:
            batch_config: Batch processing configuration
            task_manager: Task manager for executing individual tasks
            progress_manager: Optional progress manager for reporting
        """
        self.batch_config = batch_config
        self.task_manager = task_manager
        self.progress_manager = progress_manager or ProgressManager(
            batch_config.enable_progress_reporting
        )
        self.logger = logging.getLogger(f"{__name__}.BatchProcessor")
    
    async def process_batch_async(
        self,
        tasks: List[ProcessingTask]
    ) -> List[ProcessingTask]:
        """
        Process multiple tasks asynchronously with concurrency control.
        
        Executes all tasks concurrently up to the configured concurrency
        limit, with progress tracking and error handling.
        
        Args:
            tasks: List of ProcessingTask objects to process
        
        Returns:
            List of completed ProcessingTask objects with results
        
        Process Flow:
            1. Validate task list (return empty if no tasks)
            2. Create semaphore for concurrency control
            3. Create progress bar for tracking
            4. Submit all tasks with semaphore wrapper
            5. Collect results as they complete
            6. Handle errors based on continue_on_error setting
            7. Close progress bar and return results
        """
        if not tasks:
            self.logger.warning("No tasks provided for batch processing")
            return []
        
        self.logger.info(
            f"Starting async batch processing of {len(tasks)} tasks "
            f"(max concurrency: {self.batch_config.max_concurrent_tasks})"
        )
        
        # Create semaphore to limit concurrent tasks
        semaphore = asyncio.Semaphore(self.batch_config.max_concurrent_tasks)
        
        async def process_with_semaphore(task: ProcessingTask) -> ProcessingTask:
            """
            Wrapper to process task with semaphore for concurrency control.
            
            Acquires semaphore before processing, ensuring max concurrent
            tasks limit is respected. Releases semaphore after completion.
            """
            async with semaphore:
                return await self.task_manager.process_task_async(task)
        
        # Create progress bar
        progress_bar = self.progress_manager.create_progress_bar(
            total=len(tasks),
            desc="Processing documents"
        )
        
        try:
            # Submit all tasks for processing
            task_futures = [process_with_semaphore(task) for task in tasks]
            
            # Collect results as they complete
            completed_tasks = []
            for future in asyncio.as_completed(task_futures):
                try:
                    completed_task = await future
                    completed_tasks.append(completed_task)
                    progress_bar.update(1)
                    
                except Exception as e:
                    # Task-level exception (shouldn't happen as TaskManager handles errors)
                    self.logger.error(f"Unexpected error in batch task: {e}")
                    if not self.batch_config.continue_on_error:
                        # Stop processing on first error
                        raise
        
        finally:
            # Always close progress bar
            progress_bar.close()
        
        # Log batch summary
        successful = sum(1 for t in completed_tasks if t.status == ProcessingStatus.COMPLETED)
        failed = sum(1 for t in completed_tasks if t.status == ProcessingStatus.FAILED)
        
        self.logger.info(
            f"Async batch processing completed: {successful} successful, "
            f"{failed} failed out of {len(completed_tasks)} total"
        )
        
        return completed_tasks
    
    def process_batch_sync(
        self,
        tasks: List[ProcessingTask]
    ) -> List[ProcessingTask]:
        """
        Process multiple tasks synchronously with thread pool.
        
        Executes all tasks using a thread pool executor with configured
        maximum workers, providing progress tracking and error handling.
        
        Args:
            tasks: List of ProcessingTask objects to process
        
        Returns:
            List of completed ProcessingTask objects with results
        
        Process Flow:
            1. Validate task list (return empty if no tasks)
            2. Create thread pool executor
            3. Create progress bar for tracking
            4. Submit all tasks to executor
            5. Collect results as futures complete
            6. Handle errors based on continue_on_error setting
            7. Close progress bar and return results
        """
        if not tasks:
            self.logger.warning("No tasks provided for batch processing")
            return []
        
        self.logger.info(
            f"Starting sync batch processing of {len(tasks)} tasks "
            f"(max workers: {self.batch_config.max_concurrent_processors})"
        )
        
        # Create progress bar
        progress_bar = self.progress_manager.create_progress_bar(
            total=len(tasks),
            desc="Processing documents"
        )
        
        completed_tasks = []
        
        try:
            # Create thread pool executor
            with ThreadPoolExecutor(
                max_workers=self.batch_config.max_concurrent_processors
            ) as executor:
                
                # Submit all tasks
                future_to_task = {
                    executor.submit(self.task_manager.process_task_sync, task): task
                    for task in tasks
                }
                
                # Collect results as they complete
                for future in as_completed(future_to_task):
                    try:
                        completed_task = future.result()
                        completed_tasks.append(completed_task)
                        progress_bar.update(1)
                        
                    except Exception as e:
                        # Task-level exception
                        self.logger.error(f"Task execution error: {e}")
                        if not self.batch_config.continue_on_error:
                            # Stop processing on first error
                            raise
        
        finally:
            # Always close progress bar
            progress_bar.close()
        
        # Log batch summary
        successful = sum(1 for t in completed_tasks if t.status == ProcessingStatus.COMPLETED)
        failed = sum(1 for t in completed_tasks if t.status == ProcessingStatus.FAILED)
        
        self.logger.info(
            f"Sync batch processing completed: {successful} successful, "
            f"{failed} failed out of {len(completed_tasks)} total"
        )
        
        return completed_tasks
    
    def create_tasks_from_paths(
        self,
        pdf_paths: List[str],
        output_path: Optional[str] = None,
        output_filename_prefix: Optional[str] = None
    ) -> List[ProcessingTask]:
        """
        Create ProcessingTask objects from PDF file paths.
        
        Convenience method to convert a list of PDF paths into
        ProcessingTask objects ready for batch processing.
        
        Args:
            pdf_paths: List of PDF file paths
            output_path: Optional base output directory for all tasks
            output_filename_prefix: Optional prefix for output filenames
        
        Returns:
            List of ProcessingTask objects
        
        Example:
            >>> pdf_files = ["/data/doc1.pdf", "/data/doc2.pdf"]
            >>> tasks = processor.create_tasks_from_paths(
            ...     pdf_files,
            ...     output_path="/output",
            ...     output_filename_prefix="processed"
            ... )
        """
        tasks = []
        
        for i, pdf_path in enumerate(pdf_paths):
            # Construct output filename if prefix provided
            output_filename = None
            if output_filename_prefix:
                output_filename = f"{output_filename_prefix}_{i}"
            
            # Create task
            task = ProcessingTask(
                pdf_path=pdf_path,
                output_path=output_path,
                output_filename=output_filename,
                max_retries=self.batch_config.max_retries_per_task
            )
            
            tasks.append(task)
        
        return tasks

