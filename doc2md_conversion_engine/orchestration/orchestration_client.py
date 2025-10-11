#!/usr/bin/env python3
"""
Orchestration Client Module

This module provides the main client interface for document processing
orchestration. It composes all orchestration components into a cohesive
API for external use.

Purpose:
    - Provide unified interface for document processing orchestration
    - Compose task manager, batch processor, and resilience components
    - Manage component lifecycle and resource cleanup
    - Offer both single-document and batch processing capabilities
    - Support both synchronous and asynchronous processing modes

The OrchestrationClient is the primary entry point for external modules
that need to process documents with fault tolerance and scalability.
"""

import asyncio
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

from .models.processing_task import ProcessingTask
from .task_manager import TaskManager
from .batch_processor import BatchProcessor
from .resilience.circuit_breaker import CircuitBreaker
from .resilience.resource_pool import ProcessorPool
from .configuration.batch_configuration import BatchConfiguration
from .configuration.orchestration_settings import OrchestrationSettings
from .metrics.performance_tracker import PerformanceTracker
from ..utils.progress import ProgressManager


class OrchestrationClient:
    """
    Main client interface for document processing orchestration.
    
    Provides a unified API for processing single documents or batches
    with comprehensive fault tolerance, resource management, and
    performance tracking.
    
    This client composes all orchestration components and manages
    their lifecycle, providing a clean interface for external modules.
    
    Attributes:
        batch_config: Batch processing configuration
        settings: System-wide orchestration settings
        circuit_breaker: Circuit breaker for fault protection
        task_manager: Manager for individual task execution
        batch_processor: Coordinator for batch processing
        performance_tracker: Tracker for performance metrics
        processor_pool: Optional pool of processors (lazy initialized)
        logger: Logger instance
    
    Example:
        >>> # Create client with custom configuration
        >>> config = BatchConfiguration(max_concurrent_tasks=10)
        >>> client = OrchestrationClient(batch_config=config)
        >>> 
        >>> # Process single document
        >>> result = client.convert_single_pdf_to_markdown("/data/doc.pdf")
        >>> 
        >>> # Process batch
        >>> results = client.convert_pdf_batch_to_markdown([path1, path2, path3])
        >>> 
        >>> # Cleanup
        >>> client.cleanup()
    """
    
    def __init__(
        self,
        batch_config: Optional[BatchConfiguration] = None,
        settings: Optional[OrchestrationSettings] = None
    ):
        """
        Initialize orchestration client.
        
        Args:
            batch_config: Batch processing configuration (uses defaults if None)
            settings: Orchestration settings (uses defaults if None)
        """
        # Store configurations
        self.batch_config = batch_config or BatchConfiguration()
        self.settings = settings or OrchestrationSettings()
        
        # Setup logging
        self.logger = logging.getLogger(f"document_processing_engine.orchestration.orchestration_client.{self.__class__.__name__}")
        self._setup_logging()
        
        # Initialize resilience components
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.batch_config.circuit_breaker_threshold,
            timeout=self.batch_config.circuit_breaker_timeout
        )
        
        # Initialize processor pool (lazy, will be created when needed)
        self._processor_pool: Optional[ProcessorPool] = None
        
        # Initialize task manager
        self.task_manager = TaskManager(
            batch_config=self.batch_config,
            circuit_breaker=self.circuit_breaker,
            processor_pool=None  # Will be set lazily
        )
        
        # Initialize batch processor
        progress_manager = ProgressManager(self.batch_config.enable_progress_reporting)
        self.batch_processor = BatchProcessor(
            batch_config=self.batch_config,
            task_manager=self.task_manager,
            progress_manager=progress_manager
        )
        
        # Initialize performance tracker
        if self.settings.enable_metrics_collection:
            self.performance_tracker = PerformanceTracker()
        else:
            self.performance_tracker = None
        
        self.logger.info("OrchestrationClient initialized successfully")
    
    def _setup_logging(self) -> None:
        """Configure logging for the orchestration client."""
        log_level = getattr(logging, self.batch_config.log_level.upper(), logging.INFO)
        self.logger.setLevel(log_level)
        
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
    
    async def _get_processor_pool(self) -> ProcessorPool:
        """
        Get or create processor pool (lazy initialization).
        
        Creates the processor pool on first access if pooling is enabled.
        This defers expensive initialization until actually needed.
        """
        if self._processor_pool is None and self.batch_config.enable_processor_pooling:
            # Import here to avoid circular dependency
            from ..models.config import DocumentProcessingConfig
            
            # Use processor_config_kwargs from task manager if available (includes Gemini config)
            # Otherwise fallback to default config for backward compatibility
            if hasattr(self.task_manager, 'processor_config_kwargs') and self.task_manager.processor_config_kwargs is not None:
                config = DocumentProcessingConfig(**self.task_manager.processor_config_kwargs)
                self.logger.info(f"Initializing processor pool with configured settings (Gemini enabled={config.enable_gemini})")
            else:
                config = DocumentProcessingConfig()
                self.logger.debug("Initializing processor pool with default settings")
            
            self._processor_pool = ProcessorPool(
                config=config,
                pool_size=self.batch_config.processor_pool_size
            )
            await self._processor_pool.initialize()
            
            # Set pool in task manager
            self.task_manager.processor_pool = self._processor_pool
        
        return self._processor_pool
    
    def orchestrate_single_document(
        self,
        pdf_path: str,
        output_path: Optional[str] = None,
        output_filename: Optional[str] = None
    ):
        """
        Process a single document synchronously.
        
        Convenience method for processing a single document without
        creating tasks manually. Uses task manager internally.
        
        Args:
            pdf_path: Path to PDF file
            output_path: Optional output directory
            output_filename: Optional output filename (without extension)
        
        Returns:
            DocumentResult with processing outputs
        
        Raises:
            ProcessingError: If processing fails
        
        Example:
            >>> client = OrchestrationClient()
            >>> result = client.convert_single_pdf_to_markdown("/data/doc.pdf")
            >>> print(f"Processed: {result.markdown_path}")
        """
        # Create task
        task = ProcessingTask(
            pdf_path=pdf_path,
            output_path=output_path,
            output_filename=output_filename,
            max_retries=self.batch_config.max_retries_per_task
        )
        
        # Process task synchronously
        completed_task = self.task_manager.process_task_sync(task)
        
        # Update metrics
        if self.performance_tracker:
            self.performance_tracker.record_task_completion(
                success=completed_task.result is not None,
                duration=completed_task.duration,
                was_retried=completed_task.attempts > 1
            )
        
        # Return result or raise error
        if completed_task.result:
            return completed_task.result
        else:
            from ..exceptions import ProcessingError
            raise ProcessingError(f"Processing failed: {completed_task.error}")
    
    def orchestrate_document_batch(
        self,
        pdf_paths: List[str],
        output_path: Optional[str] = None,
        use_async: bool = True
    ) -> List[ProcessingTask]:
        """
        Process multiple documents (batch processing).
        
        Processes a list of PDF files with configured concurrency,
        retry logic, and fault tolerance.
        
        Args:
            pdf_paths: List of PDF file paths
            output_path: Optional base output directory
            use_async: Whether to use async processing (default: True)
        
        Returns:
            List of ProcessingTask objects with results
        
        Note:
            If use_async=True and called from within an async context,
            this will raise RuntimeError. Use orchestrate_document_batch_async()
            instead.
        
        Example:
            >>> client = OrchestrationClient()
            >>> paths = ["/data/doc1.pdf", "/data/doc2.pdf"]
            >>> tasks = client.orchestrate_document_batch(paths)
            >>> successful = [t for t in tasks if t.result]
        """
        # Create tasks from paths
        tasks = self.batch_processor.create_tasks_from_paths(
            pdf_paths=pdf_paths,
            output_path=output_path
        )
        
        # Process based on mode
        if use_async:
            # Check if we're already in an async context
            try:
                loop = asyncio.get_running_loop()
                # We're in async context, can't use asyncio.run()
                raise RuntimeError(
                    "orchestrate_document_batch with use_async=True cannot be called "
                    "from within an async context. Use orchestrate_document_batch_async() instead."
                )
            except RuntimeError as e:
                # Check if this is our error or the "no running loop" error
                if "orchestrate_document_batch" in str(e):
                    raise
                # No running loop, safe to use asyncio.run()
                return asyncio.run(self.batch_processor.process_batch_async(tasks))
        else:
            return self.batch_processor.process_batch_sync(tasks)
    
    async def orchestrate_document_batch_async(
        self,
        pdf_paths: List[str],
        output_path: Optional[str] = None
    ) -> List[ProcessingTask]:
        """
        Process multiple documents asynchronously (for use in async contexts).
        
        This is the async version of orchestrate_document_batch, designed
        to be called from within an async function or event loop.
        
        Args:
            pdf_paths: List of PDF file paths
            output_path: Optional base output directory
        
        Returns:
            List of ProcessingTask objects with results
        
        Example:
            >>> client = OrchestrationClient()
            >>> paths = ["/data/doc1.pdf", "/data/doc2.pdf"]
            >>> tasks = await client.orchestrate_document_batch_async(paths)
            >>> successful = [t for t in tasks if t.result]
        """
        # Create tasks from paths
        tasks = self.batch_processor.create_tasks_from_paths(
            pdf_paths=pdf_paths,
            output_path=output_path
        )
        
        return await self.batch_processor.process_batch_async(tasks)
    
    def orchestrate_directory_processing(
        self,
        directory_path: str,
        file_pattern: str = "*.pdf",
        output_path: Optional[str] = None,
        use_async: bool = True
    ) -> List[ProcessingTask]:
        """
        Process all PDF files in a directory.
        
        Discovers PDF files matching the pattern and processes them
        as a batch.
        
        Args:
            directory_path: Directory containing PDF files
            file_pattern: Glob pattern for file matching (default: *.pdf)
            output_path: Optional output directory
            use_async: Whether to use async processing (default: True)
        
        Returns:
            List of ProcessingTask objects with results
        
        Raises:
            ValidationError: If directory is invalid
        
        Example:
            >>> client = OrchestrationClient()
            >>> tasks = client.convert_directory_pdfs_to_markdown("/data/pdfs/")
            >>> print(f"Processed {len(tasks)} documents")
        """
        directory = Path(directory_path)
        
        if not directory.exists() or not directory.is_dir():
            from ..exceptions import ValidationError
            raise ValidationError(f"Invalid directory: {directory_path}")
        
        # Find PDF files
        pdf_files = sorted(directory.glob(file_pattern))
        
        if not pdf_files:
            self.logger.warning(
                f"No files matching '{file_pattern}' found in {directory_path}"
            )
            return []
        
        pdf_paths = [str(f) for f in pdf_files]
        self.logger.info(f"Found {len(pdf_paths)} PDF files in {directory_path}")
        
        # Process files as batch
        return self.orchestrate_document_batch(pdf_paths, output_path, use_async)
    
    def get_orchestration_metrics(self) -> Dict[str, Any]:
        """
        Get current performance metrics.
        
        Returns comprehensive performance statistics if metrics
        collection is enabled.
        
        Returns:
            Dictionary with performance metrics, or empty dict if disabled
        
        Example:
            >>> client = OrchestrationClient()
            >>> # ... process documents ...
            >>> metrics = client.get_orchestration_metrics()
            >>> print(f"Success rate: {metrics['success_rate']:.1f}%")
        """
        if self.performance_tracker:
            metrics = self.performance_tracker.get_summary()
            metrics["circuit_breaker_status"] = self.circuit_breaker.get_status()
            return metrics
        else:
            return {}
    
    def cleanup(self) -> None:
        """
        Clean up orchestration resources.
        
        Shuts down processor pool and releases other resources.
        Should be called when orchestration client is no longer needed.
        
        Example:
            >>> client = OrchestrationClient()
            >>> try:
            ...     results = client.convert_pdf_batch_to_markdown(paths)
            ... finally:
            ...     client.cleanup()
        """
        self.logger.info("Cleaning up orchestration client resources")
        
        if self._processor_pool:
            self._processor_pool.cleanup()
            self._processor_pool = None
        
        self.logger.info("Orchestration client cleanup completed")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup."""
        self.cleanup()
        return False




