#!/usr/bin/env python3
"""Data schema for chunked documents."""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from pathlib import Path

# Import LangChain Document class for proper vectorization
try:
    from langchain.schema import Document
except ImportError:
    # Fallback Document class if LangChain is not available
    @dataclass
    class Document:
        page_content: str
        metadata: Dict[str, Any]


@dataclass
class ChunkMetadata:
    """Metadata for a document chunk."""
    
    chunk_id: str
    parent_doc_id: str  # For parent chunks: source document ID; for child chunks: parent chunk ID
    doc_level: str  # "parent" or "child"
    chunk_index: Optional[int] = None
    parent_chunk_id: Optional[str] = None  # For child chunks: direct parent chunk ID
    
    # Content information
    header: str = ""
    header_level: int = 1
    section_path: str = ""
    block_types: List[str] = field(default_factory=list)
    
    # Position information
    start_line: int = 0
    end_line: int = 0
    
    # Source information
    source_path: Optional[str] = None
    pdf_stem: Optional[str] = None
    
    # Processing information
    chunking_strategy: str = "structure_aware_md_v1"
    token_count: Optional[int] = None
    
    # Custom metadata
    custom_metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary."""
        result = {
            "chunk_id": self.chunk_id,
            "parent_doc_id": self.parent_doc_id,
            "doc_level": self.doc_level,
            "chunk_index": self.chunk_index,
            "header": self.header,
            "header_level": self.header_level,
            "section_path": self.section_path,
            "block_types": self.block_types,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "source_path": self.source_path,
            "pdf_stem": self.pdf_stem,
            "chunking_strategy": self.chunking_strategy,
            "token_count": self.token_count,
        }
        
        # Add custom metadata
        result.update(self.custom_metadata)
        return result


@dataclass
class ChunkedDocument:
    """A chunked document with parent and child chunks."""
    
    source_path: str
    pdf_stem: Optional[str] = None
    
    # Chunks - Now using LangChain Document objects for proper vectorization
    parent_chunks: List[Document] = field(default_factory=list)
    child_chunks: List[Document] = field(default_factory=list)
    
    # Processing metadata
    total_parents: int = 0
    total_children: int = 0
    chunking_strategy: str = "structure_aware_md_v1"
    
    # Configuration used
    config: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        """Update counts after initialization."""
        self.total_parents = len(self.parent_chunks)
        self.total_children = len(self.child_chunks)
    
    def get_chunk_by_id(self, chunk_id: str) -> Optional[Document]:
        """Get a chunk by its ID."""
        for chunk in self.parent_chunks + self.child_chunks:
            if chunk.metadata.get("chunk_id") == chunk_id:
                return chunk
        return None
    
    def get_parent_children(self, parent_id: str) -> List[Document]:
        """Get all child chunks for a specific parent."""
        return [chunk for chunk in self.child_chunks if chunk.metadata.get("parent_chunk_id") == parent_id]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "source_path": self.source_path,
            "pdf_stem": self.pdf_stem,
            "total_parents": self.total_parents,
            "total_children": self.total_children,
            "chunking_strategy": self.chunking_strategy,
            "parent_chunks": [{"page_content": chunk.page_content, "metadata": chunk.metadata} for chunk in self.parent_chunks],
            "child_chunks": [{"page_content": chunk.page_content, "metadata": chunk.metadata} for chunk in self.child_chunks],
            "config": self.config,
        }
