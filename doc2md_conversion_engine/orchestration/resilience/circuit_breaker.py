#!/usr/bin/env python3
"""
Circuit Breaker Module

This module implements the circuit breaker pattern for fault tolerance in
the orchestration system. The circuit breaker prevents cascading failures
by temporarily blocking operations when too many failures occur.

Purpose:
    - Protect the system from cascading failures
    - Provide fast failure when underlying system is down
    - Allow automatic recovery when system becomes healthy
    - Track failure patterns for monitoring and alerting

Circuit States:
    1. CLOSED: Normal operation, requests proceed
    2. OPEN: Too many failures, requests blocked immediately
    3. HALF-OPEN: Testing if system has recovered (implicit state)

How It Works:
    - Initially in CLOSED state, operations proceed normally
    - Each failure increments the failure counter
    - When failures reach threshold, circuit OPENS
    - While OPEN, all operations fail immediately (fast failure)
    - After timeout period, circuit allows test operation
    - If test succeeds, circuit CLOSES and resets counter
    - If test fails, circuit remains OPEN and timeout resets
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class CircuitBreaker:
    """
    Implements the circuit breaker pattern for fault tolerance.
    
    The circuit breaker monitors operation failures and temporarily blocks
    all operations when failures exceed a threshold, preventing cascading
    failures and giving the underlying system time to recover.
    
    Attributes:
        failure_threshold: Number of failures before circuit opens
        timeout: Seconds to wait before attempting to close circuit
        failures: Current count of consecutive failures
        last_failure_time: Timestamp of most recent failure
        is_open: Whether circuit is currently open (blocking operations)
    
    State Transitions:
        CLOSED -> OPEN: When failures >= failure_threshold
        OPEN -> CLOSED: When timeout expires and test operation succeeds
    
    Example:
        >>> breaker = CircuitBreaker(failure_threshold=5, timeout=60.0)
        >>> 
        >>> # Check before operation
        >>> if not breaker.can_attempt():
        ...     raise Exception("Circuit breaker is open")
        >>> 
        >>> try:
        ...     perform_operation()
        ...     breaker.record_success()
        >>> except Exception:
        ...     breaker.record_failure()
    """
    
    failure_threshold: int = 5
    """
    Number of consecutive failures before circuit opens.
    
    Once this threshold is reached, the circuit breaker enters the OPEN state
    and blocks all subsequent operations until the timeout expires.
    """
    
    timeout: float = 60.0
    """
    Seconds to wait before attempting to close an open circuit.
    
    After this timeout expires, the circuit breaker allows one test operation
    to check if the underlying system has recovered.
    """
    
    failures: int = 0
    """
    Current count of consecutive failures.
    
    Incremented on each failure, reset to 0 on success or timeout.
    When this reaches failure_threshold, the circuit opens.
    """
    
    last_failure_time: Optional[float] = None
    """
    Unix timestamp of the most recent failure.
    
    Used to calculate when timeout period has elapsed and circuit
    can attempt to close. None if no failures have occurred yet.
    """
    
    is_open: bool = False
    """
    Whether the circuit is currently open (blocking operations).
    
    True: Circuit is open, operations are blocked
    False: Circuit is closed, operations can proceed
    """
    
    def record_success(self) -> None:
        """
        Record a successful operation.
        
        This method should be called after each successful operation.
        It resets the failure counter and closes the circuit if it was open,
        indicating that the underlying system has recovered.
        
        Side Effects:
            - Resets failures counter to 0
            - Closes the circuit (is_open = False)
            - Allows subsequent operations to proceed
        
        Example:
            >>> try:
            ...     result = process_document(path)
            ...     breaker.record_success()  # Reset on success
            ... except Exception:
            ...     breaker.record_failure()
        """
        self.failures = 0
        self.is_open = False
    
    def record_failure(self) -> None:
        """
        Record a failed operation.
        
        This method should be called after each failed operation.
        It increments the failure counter and opens the circuit if
        the failure threshold is reached.
        
        Side Effects:
            - Increments failures counter
            - Updates last_failure_time to current timestamp
            - Opens circuit if failures >= failure_threshold
        
        Example:
            >>> try:
            ...     result = process_document(path)
            ...     breaker.record_success()
            ... except Exception as e:
            ...     breaker.record_failure()  # Track failure
            ...     raise
        """
        self.failures += 1
        self.last_failure_time = time.time()
        
        # Check if failure threshold reached
        if self.failures >= self.failure_threshold:
            self.is_open = True
    
    def can_attempt(self) -> bool:
        """
        Check if an operation can be attempted.
        
        Determines whether the circuit breaker will allow an operation
        to proceed based on the current state and timing.
        
        Logic:
            1. If circuit is CLOSED (not open), allow operation
            2. If circuit is OPEN but timeout has elapsed:
               - Close the circuit (allow test operation)
               - Reset failure counter
               - Return True
            3. If circuit is OPEN and timeout has not elapsed:
               - Return False (block operation)
        
        Returns:
            True if operation can proceed, False if blocked
        
        Example:
            >>> if breaker.can_attempt():
            ...     perform_operation()
            ... else:
            ...     raise Exception("Circuit breaker is open, try again later")
        """
        # Circuit is closed, allow operation
        if not self.is_open:
            return True
        
        # Circuit is open, check if timeout has elapsed
        if self.last_failure_time and (time.time() - self.last_failure_time) > self.timeout:
            # Timeout elapsed, close circuit for test operation
            self.is_open = False
            self.failures = 0
            return True
        
        # Circuit is open and timeout has not elapsed, block operation
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get current circuit breaker status information.
        
        Provides a snapshot of the circuit breaker's current state,
        useful for monitoring, logging, and debugging.
        
        Returns:
            Dictionary containing:
                - is_open: Boolean indicating if circuit is open
                - failures: Current failure count
                - threshold: Configured failure threshold
                - time_until_reset: Seconds until circuit can close (if open)
        
        Example:
            >>> status = breaker.get_status()
            >>> print(f"Circuit open: {status['is_open']}")
            >>> print(f"Failures: {status['failures']}/{status['threshold']}")
            >>> if status['is_open']:
            ...     print(f"Retry in {status['time_until_reset']:.1f} seconds")
        """
        # Calculate time until circuit can attempt to close
        time_until_reset = 0.0
        if self.is_open and self.last_failure_time:
            elapsed = time.time() - self.last_failure_time
            time_until_reset = max(0.0, self.timeout - elapsed)
        
        return {
            "is_open": self.is_open,
            "failures": self.failures,
            "threshold": self.failure_threshold,
            "time_until_reset": time_until_reset
        }


