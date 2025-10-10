#!/usr/bin/env python3
"""
Retry Handler Module

This module provides retry logic with configurable backoff strategies for
failed operations in the orchestration system. It handles the complexity
of retry timing, attempt tracking, and exponential backoff calculations.

Purpose:
    - Implement retry logic with multiple backoff strategies
    - Calculate appropriate delays between retry attempts
    - Track retry attempts and determine retry eligibility
    - Support both synchronous and asynchronous retry patterns

Retry Strategies:
    1. Fixed Delay: Same delay between all retries (e.g., 2s, 2s, 2s)
    2. Exponential Backoff: Delay doubles each time (e.g., 2s, 4s, 8s)
    3. Linear Backoff: Delay increases linearly (e.g., 2s, 4s, 6s)

When to Use:
    - Transient failures (network timeouts, temporary unavailability)
    - Rate limiting scenarios (need to slow down requests)
    - Resource contention (system temporarily overloaded)
"""

import asyncio
import time
from typing import Optional
from dataclasses import dataclass


@dataclass
class RetryStrategy:
    """
    Configuration for retry behavior and backoff strategy.
    
    Defines how retry attempts should be spaced and when to stop retrying.
    Used by RetryHandler to determine delay durations and retry eligibility.
    
    Attributes:
        max_attempts: Maximum total attempts (initial + retries)
        base_delay: Base delay in seconds between attempts
        use_exponential_backoff: Use exponential backoff (delay doubles)
        use_linear_backoff: Use linear backoff (delay increases linearly)
        max_delay: Maximum delay cap in seconds (prevents excessive waits)
    
    Example:
        >>> # Exponential backoff: 2s, 4s, 8s, 16s (capped at 30s)
        >>> strategy = RetryStrategy(
        ...     max_attempts=5,
        ...     base_delay=2.0,
        ...     use_exponential_backoff=True,
        ...     max_delay=30.0
        ... )
    """
    
    max_attempts: int = 3
    """Maximum number of total attempts (includes initial attempt)."""
    
    base_delay: float = 2.0
    """Base delay in seconds between retry attempts."""
    
    use_exponential_backoff: bool = True
    """
    Use exponential backoff strategy.
    
    Delays: base * 2^(attempt-1)
    Example with base=2: 2s, 4s, 8s, 16s, ...
    """
    
    use_linear_backoff: bool = False
    """
    Use linear backoff strategy.
    
    Delays: base * attempt
    Example with base=2: 2s, 4s, 6s, 8s, ...
    Note: Only used if use_exponential_backoff is False.
    """
    
    max_delay: float = 60.0
    """
    Maximum delay cap in seconds.
    
    Prevents exponential backoff from creating excessively long delays.
    Actual delay will never exceed this value.
    """


class RetryHandler:
    """
    Handles retry logic with configurable backoff strategies.
    
    This class encapsulates the complexity of retry timing calculations,
    attempt tracking, and sleep operations for both sync and async contexts.
    
    The handler uses a RetryStrategy to determine delays and eligibility,
    making it easy to test different retry approaches without changing
    the calling code.
    
    Attributes:
        strategy: RetryStrategy defining retry behavior
    
    Example:
        >>> handler = RetryHandler(RetryStrategy(max_attempts=3))
        >>> 
        >>> attempt = 0
        >>> while attempt < handler.strategy.max_attempts:
        ...     attempt += 1
        ...     try:
        ...         result = risky_operation()
        ...         break
        ...     except Exception as e:
        ...         if attempt < handler.strategy.max_attempts:
        ...             delay = handler.calculate_delay(attempt)
        ...             time.sleep(delay)
    """
    
    def __init__(self, strategy: Optional[RetryStrategy] = None):
        """
        Initialize retry handler with strategy.
        
        Args:
            strategy: RetryStrategy object, or None for default strategy
        """
        self.strategy = strategy or RetryStrategy()
    
    def calculate_delay(self, attempt_number: int) -> float:
        """
        Calculate delay duration for a specific retry attempt.
        
        Computes the appropriate delay based on the configured backoff
        strategy (exponential, linear, or fixed). The delay is capped
        at the strategy's max_delay value.
        
        Args:
            attempt_number: Current attempt number (1-indexed)
                1 = first retry (after initial attempt)
                2 = second retry
                etc.
        
        Returns:
            Delay duration in seconds (float)
        
        Calculation Logic:
            1. If exponential_backoff: delay = base * (2 ** (attempt - 1))
            2. Else if linear_backoff: delay = base * attempt
            3. Else (fixed): delay = base
            4. Cap delay at max_delay
        
        Example:
            >>> handler = RetryHandler(RetryStrategy(
            ...     base_delay=2.0,
            ...     use_exponential_backoff=True,
            ...     max_delay=30.0
            ... ))
            >>> 
            >>> handler.calculate_delay(1)  # First retry: 2s
            2.0
            >>> handler.calculate_delay(2)  # Second retry: 4s
            4.0
            >>> handler.calculate_delay(3)  # Third retry: 8s
            8.0
            >>> handler.calculate_delay(10)  # Would be 1024s, capped at 30s
            30.0
        """
        # Start with base delay
        delay = self.strategy.base_delay
        
        # Apply backoff strategy
        if self.strategy.use_exponential_backoff:
            # Exponential: delay doubles each time
            # Cap exponent to prevent overflow
            # max_delay / base_delay = max multiplier
            max_exponent = int(self.strategy.max_delay / self.strategy.base_delay).bit_length()
            safe_exponent = min(attempt_number - 1, max_exponent)
            delay = self.strategy.base_delay * (2 ** safe_exponent)
        elif self.strategy.use_linear_backoff:
            # Linear: delay increases by base each time
            # delay = base * attempt
            delay = self.strategy.base_delay * attempt_number
        # else: Fixed delay (no change needed)
        
        # Cap delay at maximum to prevent excessive waits
        return min(delay, self.strategy.max_delay)
    
    def should_retry(self, current_attempt: int) -> bool:
        """
        Determine if another retry attempt should be made.
        
        Checks if the current attempt number is below the maximum
        allowed attempts defined in the strategy.
        
        Args:
            current_attempt: Number of attempts made so far (1-indexed)
        
        Returns:
            True if another retry is allowed, False otherwise
        
        Example:
            >>> handler = RetryHandler(RetryStrategy(max_attempts=3))
            >>> 
            >>> handler.should_retry(1)  # After 1st attempt
            True
            >>> handler.should_retry(2)  # After 2nd attempt
            True
            >>> handler.should_retry(3)  # After 3rd attempt (max)
            False
        """
        return current_attempt < self.strategy.max_attempts
    
    def sleep_before_retry(self, attempt_number: int) -> None:
        """
        Sleep for appropriate duration before retry attempt (synchronous).
        
        Calculates the delay using the configured backoff strategy and
        blocks the current thread for that duration.
        
        Args:
            attempt_number: Current retry attempt number (1-indexed)
        
        Side Effects:
            Blocks current thread for calculated delay duration
        
        Example:
            >>> handler = RetryHandler(RetryStrategy(base_delay=2.0))
            >>> 
            >>> for attempt in range(1, 4):
            ...     try:
            ...         result = operation()
            ...         break
            ...     except Exception:
            ...         if handler.should_retry(attempt):
            ...             handler.sleep_before_retry(attempt)
        """
        delay = self.calculate_delay(attempt_number)
        time.sleep(delay)
    
    async def sleep_before_retry_async(self, attempt_number: int) -> None:
        """
        Sleep for appropriate duration before retry attempt (asynchronous).
        
        Calculates the delay using the configured backoff strategy and
        asynchronously sleeps for that duration without blocking the
        event loop.
        
        Args:
            attempt_number: Current retry attempt number (1-indexed)
        
        Side Effects:
            Asynchronously sleeps for calculated delay duration
        
        Example:
            >>> handler = RetryHandler(RetryStrategy(base_delay=2.0))
            >>> 
            >>> for attempt in range(1, 4):
            ...     try:
            ...         result = await async_operation()
            ...         break
            ...     except Exception:
            ...         if handler.should_retry(attempt):
            ...             await handler.sleep_before_retry_async(attempt)
        """
        delay = self.calculate_delay(attempt_number)
        await asyncio.sleep(delay)
    
    def get_remaining_attempts(self, current_attempt: int) -> int:
        """
        Get number of retry attempts remaining.
        
        Args:
            current_attempt: Number of attempts made so far (1-indexed)
        
        Returns:
            Number of retry attempts still available
        
        Example:
            >>> handler = RetryHandler(RetryStrategy(max_attempts=5))
            >>> 
            >>> handler.get_remaining_attempts(1)  # After 1st attempt
            4
            >>> handler.get_remaining_attempts(3)  # After 3rd attempt
            2
            >>> handler.get_remaining_attempts(5)  # After 5th attempt
            0
        """
        return max(0, self.strategy.max_attempts - current_attempt)




