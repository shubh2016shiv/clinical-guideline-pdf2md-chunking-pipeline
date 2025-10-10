#!/usr/bin/env python3
"""Base exception classes for the document chunker module."""

from typing import Optional, Dict, Any


class DocumentChunkerError(Exception):
    """Base exception for all document chunker errors."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.context = context or {}
    
    def __str__(self) -> str:
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{self.message} | Context: {context_str}"
        return self.message
