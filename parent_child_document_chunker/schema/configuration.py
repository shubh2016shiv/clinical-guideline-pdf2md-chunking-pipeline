#!/usr/bin/env python3
"""Configuration schema for the document chunker module."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChunkingConfig:
    """Configuration for document chunking operations."""
    
    # Token limits
    child_token_limit: int = 450
    child_overlap_tokens: int = 40
    min_chunk_tokens: int = 60
    
    # Output options
    output_format: str = "json"  # "json", "markdown", "csv"
    include_metadata: bool = True
    save_chunks_to_files: bool = False
    output_directory: str = "chunked_documents"
    
    # Processing options
    enable_progress: bool = True
    parallel_processing: bool = False
    max_workers: int = 4
    
    # Validation
    validate_input: bool = True
    strict_mode: bool = False
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.child_token_limit <= 0:
            raise ValueError("child_token_limit must be positive")
        if self.child_overlap_tokens < 0:
            raise ValueError("child_overlap_tokens must be non-negative")
        if self.min_chunk_tokens <= 0:
            raise ValueError("min_chunk_tokens must be positive")
        if self.child_overlap_tokens >= self.child_token_limit:
            raise ValueError("child_overlap_tokens must be less than child_token_limit")
        if self.max_workers <= 0:
            raise ValueError("max_workers must be positive")
