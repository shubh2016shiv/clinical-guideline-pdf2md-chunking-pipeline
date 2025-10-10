#!/usr/bin/env python3
"""Data schema for the document chunker module."""

from .configuration import ChunkingConfig
from .document_chunks import ChunkedDocument, ChunkMetadata

__all__ = [
    "ChunkingConfig",
    "ChunkedDocument", 
    "ChunkMetadata",
]
