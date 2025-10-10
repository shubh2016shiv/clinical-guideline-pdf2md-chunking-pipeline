#!/usr/bin/env python3
"""Data schema for the guideline processor module."""

from .config import DocumentProcessingConfig
from .document import (
    DocumentResult,
    ProcessingMetadata,
    ImageNote,
    TableNote,
    HeaderInfo
)

__all__ = [
    "DocumentProcessingConfig",
    "DocumentResult", 
    "ProcessingMetadata",
    "ImageNote",
    "TableNote",
    "HeaderInfo",
]
