#!/usr/bin/env python3
"""Processing-specific exceptions for the document chunker module."""

from typing import Optional, Any
from .base_exceptions import DocumentChunkerError


class ChunkingError(DocumentChunkerError):
    """Raised when document chunking fails."""
    
    def __init__(self, message: str, document_path: Optional[str] = None, **kwargs):
        context = {"document_path": document_path, **kwargs}
        super().__init__(message, context)


class ValidationError(DocumentChunkerError):
    """Raised when input validation fails."""
    
    def __init__(self, message: str, field: Optional[str] = None, value: Optional[Any] = None, **kwargs):
        context = {"field": field, "value": value, **kwargs}
        super().__init__(message, context)


class FileError(DocumentChunkerError):
    """Raised when file operations fail."""
    
    def __init__(self, message: str, file_path: Optional[str] = None, operation: Optional[str] = None, **kwargs):
        context = {"file_path": file_path, "operation": operation, **kwargs}
        super().__init__(message, context)
