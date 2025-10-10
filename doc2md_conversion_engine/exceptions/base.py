#!/usr/bin/env python3
"""Base exception class for the guideline processor module."""

from typing import Optional, Any, Dict


class GuidelineProcessorError(Exception):
    """
    Base exception class for all guideline processor errors.
    
    This exception provides a standardized way to handle errors across
    the module with additional context and debugging information.
    """
    
    def __init__(
        self, 
        message: str, 
        error_code: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ) -> None:
        """
        Initialize the exception.
        
        Args:
            message: Human-readable error message
            error_code: Optional error code for programmatic handling
            context: Optional dictionary with additional context
            original_exception: Optional original exception that caused this
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.context = context or {}
        self.original_exception = original_exception
        
    def __str__(self) -> str:
        """Return string representation with context."""
        base = f"GuidelineProcessorError: {self.message}"
        if self.error_code:
            base += f" (Code: {self.error_code})"
        if self.context:
            base += f" | Context: {self.context}"
        return base
        
    def __repr__(self) -> str:
        """Return detailed representation for debugging."""
        return (
            f"GuidelineProcessorError("
            f"message='{self.message}', "
            f"error_code='{self.error_code}', "
            f"context={self.context}, "
            f"original_exception={self.original_exception})"
        )
