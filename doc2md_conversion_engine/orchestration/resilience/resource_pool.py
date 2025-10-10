#!/usr/bin/env python3
"""
Resource Pool Module

This module implements a resource pooling pattern for document processors,
enabling efficient reuse of processor instances across multiple processing
tasks. Pooling significantly reduces initialization overhead and improves
throughput in batch processing scenarios.

Purpose:
    - Maintain a pool of initialized processor instances
    - Enable efficient resource acquisition and release
    - Reduce initialization overhead per task
    - Support concurrent access with proper synchronization
    - Manage processor lifecycle (initialization, cleanup)

Benefits of Pooling:
    - Faster task processing (no repeated initialization)
    - Lower memory overhead (fixed number of instances)
    - Better resource utilization (instances stay warm)
    - Predictable resource consumption

When to Use:
    - Batch processing with many documents
    - High-throughput scenarios
    - When processor initialization is expensive
    - Production environments with consistent load
"""

import asyncio
import logging
from typing import List, Optional


class ProcessorPool:
    """
    Pool of document processors for resource optimization.
    
    Maintains a fixed-size pool of initialized document processor instances
    that can be acquired and released by tasks. This eliminates the overhead
    of creating a new processor for each document, significantly improving
    throughput in batch processing operations.
    
    The pool uses an asyncio.Queue for thread-safe processor management,
    ensuring proper synchronization in concurrent processing scenarios.
    
    Lifecycle:
        1. __init__: Configure pool but don't create processors yet
        2. initialize: Create all processors and add to available queue
        3. acquire: Get a processor from pool (blocks if all in use)
        4. release: Return processor to pool for reuse
        5. cleanup: Shutdown all processors and clear pool
    
    Attributes:
        config: Document processing configuration for creating processors
        pool_size: Number of processors to maintain in pool
        processors: List of all processor instances (initialized or not)
        available: Queue of processors ready for use
        logger: Logger instance for pool operations
        _initialized: Whether pool has been initialized
    
    Example:
        >>> pool = ProcessorPool(config, pool_size=3)
        >>> await pool.initialize()  # Create 3 processors
        >>> 
        >>> # Acquire processor for use
        >>> processor = await pool.acquire()
        >>> try:
        ...     result = processor.convert_single_pdf_to_markdown(path)
        ... finally:
        ...     await pool.release(processor)  # Return to pool
        >>> 
        >>> pool.cleanup()  # Shutdown all processors
    """
    
    def __init__(self, config, pool_size: int):
        """
        Initialize processor pool configuration.
        
        Note: This only configures the pool. Actual processor instances
        are created later when initialize() is called. This lazy
        initialization pattern allows for better control of timing.
        
        Args:
            config: DocumentProcessingConfig for creating processors
            pool_size: Number of processors to maintain in the pool
        
        Example:
            >>> from models.config import DocumentProcessingConfig
            >>> config = DocumentProcessingConfig()
            >>> pool = ProcessorPool(config, pool_size=5)
        """
        self.config = config
        self.pool_size = pool_size
        
        # List of all processor instances (empty until initialized)
        self.processors: List = []  # Type: List[DocumentProcessor]
        
        # Queue of available processors (thread-safe)
        # maxsize limits queue to pool_size
        self.available: asyncio.Queue = asyncio.Queue(maxsize=pool_size)
        
        # Logger for pool operations
        self.logger = logging.getLogger(f"{__name__}.ProcessorPool")
        
        # Track initialization state
        self._initialized = False
    
    async def initialize(self) -> None:
        """
        Initialize the processor pool by creating all processor instances.
        
        Creates pool_size processor instances and adds them to the
        available queue, making them ready for use. This is an expensive
        operation as it initializes all processors up front.
        
        Side Effects:
            - Creates pool_size processor instances
            - Adds all processors to available queue
            - Sets _initialized to True
            - Logs initialization progress
        
        Thread Safety:
            Can be called multiple times safely (subsequent calls are no-ops).
        
        Example:
            >>> pool = ProcessorPool(config, pool_size=3)
            >>> await pool.initialize()
            # INFO | Initializing processor pool with 3 processors
            # INFO | Processor pool initialized successfully
        """
        # Skip if already initialized (idempotent)
        if self._initialized:
            return
        
        self.logger.info(f"Initializing processor pool with {self.pool_size} processors")
        
        # Import here to avoid circular dependency
        from ...engine.document_processor import DocumentProcessor
        
        # Create all processor instances
        for i in range(self.pool_size):
            # Create new processor with shared configuration
            processor = DocumentProcessor(self.config)
            
            # Add to processors list for tracking
            self.processors.append(processor)
            
            # Add to available queue (ready for use)
            await self.available.put(processor)
        
        # Mark pool as initialized
        self._initialized = True
        self.logger.info("Processor pool initialized successfully")
    
    async def acquire(self):
        """
        Acquire a processor from the pool for use.
        
        Retrieves a processor from the available queue. If no processors
        are currently available (all in use), this method blocks until
        one becomes available via release().
        
        Returns:
            DocumentProcessor instance ready for use
        
        Blocking Behavior:
            This method will block if all processors are currently in use.
            Use with asyncio.wait_for() if you need a timeout.
        
        Thread Safety:
            Safe to call from multiple concurrent tasks. The asyncio.Queue
            handles synchronization automatically.
        
        Example:
            >>> # Simple acquisition
            >>> processor = await pool.acquire()
            >>> result = processor.convert_single_pdf_to_markdown(path)
            >>> await pool.release(processor)
            >>> 
            >>> # With timeout
            >>> try:
            ...     processor = await asyncio.wait_for(
            ...         pool.acquire(),
            ...         timeout=30.0
            ...     )
            ... except asyncio.TimeoutError:
            ...     print("No processor available within 30 seconds")
        """
        # Ensure pool is initialized before acquiring
        if not self._initialized:
            await self.initialize()
        
        # Get processor from queue (blocks if empty)
        processor = await self.available.get()
        return processor
    
    async def release(self, processor) -> None:
        """
        Release a processor back to the pool for reuse.
        
        Returns a processor to the available queue, making it available
        for other tasks. This should always be called after using a
        processor, typically in a finally block.
        
        Args:
            processor: DocumentProcessor instance to return to pool
        
        Thread Safety:
            Safe to call from multiple concurrent tasks.
        
        Example:
            >>> processor = await pool.acquire()
            >>> try:
            ...     result = processor.convert_single_pdf_to_markdown(path)
            ... finally:
            ...     await pool.release(processor)  # Always release
        """
        # Return processor to available queue
        await self.available.put(processor)
    
    def cleanup(self) -> None:
        """
        Clean up all processors in the pool.
        
        Shuts down all processor instances and clears the pool, releasing
        all resources. This should be called when the pool is no longer
        needed, typically at application shutdown.
        
        Side Effects:
            - Calls shutdown() on all processors
            - Clears processors list
            - Clears available queue (implicitly)
            - Sets _initialized to False
            - Logs cleanup progress and any errors
        
        Error Handling:
            Continues cleanup even if individual processors fail to shutdown,
            logging warnings for any failures.
        
        Example:
            >>> pool = ProcessorPool(config, pool_size=3)
            >>> await pool.initialize()
            >>> # ... use pool ...
            >>> pool.cleanup()  # Release all resources
        """
        self.logger.info("Cleaning up processor pool")
        
        # Shutdown each processor, catching and logging errors
        for processor in self.processors:
            try:
                processor.shutdown()
            except Exception as e:
                # Log but continue cleanup
                self.logger.warning(f"Error shutting down processor: {e}")
        
        # Clear the processors list
        self.processors.clear()
        
        # Reset initialization flag
        self._initialized = False
        
        self.logger.info("Processor pool cleanup completed")




