#!/usr/bin/env python3
"""Processing-related exceptions for the guideline processor module."""

from .base import GuidelineProcessorError
from typing import Optional, Any, Dict


class ProcessingError(GuidelineProcessorError):
    """Raised when there's an error during document processing."""
    
    def __init__(
        self, 
        message: str, 
        stage: Optional[str] = None,
        document_path: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        Initialize processing error.
        
        Args:
            message: Error message
            stage: The processing stage where the error occurred
            document_path: Path to the document being processed
            **kwargs: Additional context
        """
        context = kwargs.get('context', {})
        if stage:
            context['processing_stage'] = stage
        if document_path:
            context['document_path'] = document_path
            
        super().__init__(
            message=message,
            error_code="PROCESSING_ERROR",
            context=context,
            **kwargs
        )


class DocumentLoadError(ProcessingError):
    """Raised when a document cannot be loaded."""
    
    def __init__(self, document_path: str, reason: str, **kwargs) -> None:
        """
        Initialize document load error.
        
        Args:
            document_path: Path to the document that couldn't be loaded
            reason: Reason for the load failure
            **kwargs: Additional context
        """
        super().__init__(
            message=f"Failed to load document '{document_path}': {reason}",
            document_path=document_path,
            error_code="DOCUMENT_LOAD_ERROR",
            context={'reason': reason, **kwargs.get('context', {})},
            **kwargs
        )


class ConversionError(ProcessingError):
    """Raised when document conversion fails."""
    
    def __init__(
        self, 
        stage: str, 
        reason: str, 
        document_path: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        Initialize conversion error.
        
        Args:
            stage: The conversion stage that failed
            reason: Reason for the conversion failure
            document_path: Path to the document being converted
            **kwargs: Additional context
        """
        super().__init__(
            message=f"Conversion failed at stage '{stage}': {reason}",
            stage=stage,
            document_path=document_path,
            error_code="CONVERSION_ERROR",
            context={'reason': reason, **kwargs.get('context', {})},
            **kwargs
        )


class OutputError(ProcessingError):
    """Raised when output generation fails."""
    
    def __init__(
        self, 
        output_path: str, 
        reason: str, 
        document_path: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        Initialize output error.
        
        Args:
            output_path: Path where output was supposed to be written
            reason: Reason for the output failure
            document_path: Path to the source document
            **kwargs: Additional context
        """
        super().__init__(
            message=f"Failed to generate output '{output_path}': {reason}",
            stage="output_generation",
            document_path=document_path,
            error_code="OUTPUT_ERROR",
            context={'output_path': output_path, 'reason': reason, **kwargs.get('context', {})},
            **kwargs
        )
