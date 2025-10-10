#!/usr/bin/env python3
"""
Resilience Package

This package contains fault tolerance and resilience components for the
orchestration system, including circuit breakers, retry logic, and
resource pooling.

Exported Classes:
    - CircuitBreaker: Implements circuit breaker pattern for fault tolerance
    - RetryHandler: Handles retry logic with configurable backoff strategies
    - RetryStrategy: Configuration for retry behavior
    - ProcessorPool: Pool of processors for resource optimization

Usage:
    from doc2md_conversion_engine.orchestration.resilience import (
        CircuitBreaker,
        RetryHandler,
        RetryStrategy,
        ProcessorPool
    )
    
    # Circuit breaker for protecting against cascading failures
    breaker = CircuitBreaker(failure_threshold=5, timeout=60.0)
    
    # Retry handler with exponential backoff
    retry_handler = RetryHandler(RetryStrategy(
        max_attempts=3,
        base_delay=2.0,
        use_exponential_backoff=True
    ))
    
    # Processor pool for efficient resource usage
    pool = ProcessorPool(config, pool_size=5)
"""

from .circuit_breaker import CircuitBreaker
from .retry_handler import RetryHandler, RetryStrategy
from .resource_pool import ProcessorPool

__all__ = [
    "CircuitBreaker",
    "RetryHandler",
    "RetryStrategy",
    "ProcessorPool",
]




