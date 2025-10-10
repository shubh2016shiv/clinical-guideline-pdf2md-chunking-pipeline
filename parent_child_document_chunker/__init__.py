#!/usr/bin/env python3
"""
Document Chunker Module

A professional, enterprise-grade module for structure-aware parent/child chunking
of markdown documents. This module provides intelligent chunking that preserves
document hierarchy while creating searchable, manageable content chunks.

Features:
- Structure-aware chunking based on markdown headers
- Parent/child relationship preservation
- Configurable token limits and overlap
- Parallel processing support
- Comprehensive metadata tracking
- Progress monitoring and logging
- Multiple output formats

Usage:
    from parent_child_document_chunker import DocumentChunker, ChunkingConfig
    
    # Configure chunking
    config = ChunkingConfig(
        child_token_limit=450,
        child_overlap_tokens=40,
        parallel_processing=True
    )
    
    # Initialize chunker
    chunker = DocumentChunker(config)
    
    # Chunk a single file
    result = chunker.chunk_file("document.md")
    
    # Chunk a directory
    results = chunker.chunk_directory("out/", recursive=True)
"""

from __future__ import annotations

# Core imports
from .engine.markdown_parser import StructureAwareChunker
from .engine.chunking_processor import DocumentChunker
from .schema.configuration import ChunkingConfig
from .schema.document_chunks import ChunkedDocument, ChunkMetadata, Document

# Utility imports
from .utilities.file_operations import validate_markdown_file, ensure_directory
from .utilities.progress_tracking import ProgressManager

# Exception imports
from .exceptions import DocumentChunkerError, ChunkingError, ValidationError, FileError

__version__ = "1.0.0"
__author__ = "Document Chunker Team"

__all__ = [
    # Core classes
    "StructureAwareChunker",
    "DocumentChunker",
    
    # Configuration and schema
    "ChunkingConfig",
    "ChunkedDocument", 
    "ChunkMetadata",
    "Document",
    
    # Utilities
    "validate_markdown_file",
    "ensure_directory",
    "ProgressManager",
    
    # Exceptions
    "DocumentChunkerError",
    "ChunkingError",
    "ValidationError", 
    "FileError",
]
