#!/usr/bin/env python3
"""Validation-related exceptions for the guideline processor module."""

from .base import GuidelineProcessorError
from typing import Optional, Any, Dict


class ValidationError(GuidelineProcessorError):
    """Raised when input validation fails."""
    
    def __init__(
        self, 
        message: str, 
        field: Optional[str] = None,
        value: Optional[Any] = None,
        **kwargs
    ) -> None:
        """
        Initialize validation error.
        
        Args:
            message: Error message
            field: The field that failed validation
            value: The value that failed validation
            **kwargs: Additional context
        """
        context = kwargs.get('context', {})
        if field:
            context['field'] = field
        if value is not None:
            context['value'] = value
            
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            context=context,
            **kwargs
        )


class FileValidationError(ValidationError):
    """Raised when file validation fails."""
    
    def __init__(
        self, 
        file_path: str, 
        reason: str, 
        expected_format: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        Initialize file validation error.
        
        Args:
            file_path: Path to the file that failed validation
            reason: Reason for validation failure
            expected_format: Expected file format
            **kwargs: Additional context
        """
        super().__init__(
            message=f"File validation failed for '{file_path}': {reason}",
            field="file_path",
            value=file_path,
            error_code="FILE_VALIDATION_ERROR",
            context={
                'reason': reason,
                'expected_format': expected_format,
                **kwargs.get('context', {})
            },
            **kwargs
        )


class ContentValidationError(ValidationError):
    """Raised when document content validation fails."""
    
    def __init__(
        self, 
        content_type: str, 
        reason: str, 
        location: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        Initialize content validation error.
        
        Args:
            content_type: Type of content that failed validation
            reason: Reason for validation failure
            location: Location in document where validation failed
            **kwargs: Additional context
        """
        super().__init__(
            message=f"Content validation failed for {content_type}: {reason}",
            field="content",
            error_code="CONTENT_VALIDATION_ERROR",
            context={
                'content_type': content_type,
                'reason': reason,
                'location': location,
                **kwargs.get('context', {})
            },
            **kwargs
        )
