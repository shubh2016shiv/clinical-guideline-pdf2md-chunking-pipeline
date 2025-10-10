#!/usr/bin/env python3
"""Document data schema for the guideline processor module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from pathlib import Path


@dataclass
class HeaderInfo:
    """Information about a document header/section."""
    
    page: int
    y_position: float
    level: int
    title: str
    reference: str
    
    def __post_init__(self) -> None:
        """Validate header information."""
        if self.page < 1:
            raise ValueError("Page number must be positive")
        if self.level < 1:
            raise ValueError("Header level must be positive")
        if not self.title.strip():
            raise ValueError("Header title cannot be empty")


@dataclass
class ImageNote:
    """Information about an extracted image/figure."""
    
    page: int
    figure_id: str
    caption: str
    summary: str
    section_anchor: str
    section_ref: str
    figure_label: Optional[str] = None
    section_topic: Optional[str] = None
    image_path: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validate image note."""
        if self.page < 1:
            raise ValueError("Page number must be positive")
        if not self.figure_id.strip():
            raise ValueError("Figure ID cannot be empty")
        if not self.summary.strip():
            raise ValueError("Summary cannot be empty")
    
    @property
    def has_image(self) -> bool:
        """Check if image file exists."""
        if not self.image_path:
            return False
        return Path(self.image_path).exists()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'page': self.page,
            'figure_id': self.figure_id,
            'caption': self.caption,
            'summary': self.summary,
            'section_anchor': self.section_anchor,
            'section_ref': self.section_ref,
            'figure_label': self.figure_label,
            'section_topic': self.section_topic,
            'image_path': self.image_path,
            'has_image': self.has_image,
        }


@dataclass
class TableNote:
    """Information about an extracted table."""
    
    page: int
    table_id: str
    markdown: str
    csv_path: Optional[str]
    section_anchor: str
    section_ref: str
    
    def __post_init__(self) -> None:
        """Validate table note."""
        if self.page < 1:
            raise ValueError("Page number must be positive")
        if not self.table_id.strip():
            raise ValueError("Table ID cannot be empty")
        if not self.markdown.strip():
            raise ValueError("Markdown content cannot be empty")
    
    @property
    def has_csv(self) -> bool:
        """Check if CSV file exists."""
        if not self.csv_path:
            return False
        return Path(self.csv_path).exists()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'page': self.page,
            'table_id': self.table_id,
            'markdown': self.markdown,
            'csv_path': self.csv_path,
            'section_anchor': self.section_anchor,
            'section_ref': self.section_ref,
            'has_csv': self.has_csv,
        }


@dataclass
class ProcessingMetadata:
    """Metadata about the processing operation."""
    
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    total_pages: int = 0
    total_figures: int = 0
    total_tables: int = 0
    processing_stages: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    @property
    def duration(self) -> Optional[float]:
        """Get processing duration in seconds."""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None
    
    @property
    def success(self) -> bool:
        """Check if processing was successful."""
        return len(self.errors) == 0
    
    def add_stage(self, stage: str) -> None:
        """Add a processing stage."""
        self.processing_stages.append(stage)
    
    def add_error(self, error: str) -> None:
        """Add an error message."""
        self.errors.append(error)
    
    def add_warning(self, warning: str) -> None:
        """Add a warning message."""
        self.warnings.append(warning)
    
    def complete(self) -> None:
        """Mark processing as complete."""
        self.end_time = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration': self.duration,
            'total_pages': self.total_pages,
            'total_figures': self.total_figures,
            'total_tables': self.total_tables,
            'processing_stages': self.processing_stages,
            'errors': self.errors,
            'warnings': self.warnings,
            'success': self.success,
        }


@dataclass
class DocumentResult:
    """Result of document processing."""
    
    # Input information
    input_path: str
    input_filename: str
    
    # Output information
    markdown_path: str
    figures_dir: Optional[str] = None
    
    # Extracted content
    figures: List[ImageNote] = field(default_factory=list)
    tables: List[TableNote] = field(default_factory=list)
    headers: List[HeaderInfo] = field(default_factory=list)
    
    # Processing metadata
    metadata: ProcessingMetadata = field(default_factory=ProcessingMetadata)
    
    # Additional data
    raw_markdown: Optional[str] = None
    docling_document: Optional[Any] = None
    
    def __post_init__(self) -> None:
        """Validate document result."""
        if not self.input_path:
            raise ValueError("Input path cannot be empty")
        if not self.markdown_path:
            raise ValueError("Markdown path cannot be empty")
        
        # Set input filename if not provided
        if not self.input_filename:
            self.input_filename = Path(self.input_path).name
        
        # Update metadata counts
        self.metadata.total_figures = len(self.figures)
        self.metadata.total_tables = len(self.tables)
        self.metadata.total_pages = max(
            [h.page for h in self.headers] + [0]
        )
    
    @property
    def pdf_stem(self) -> str:
        """Get PDF filename without extension."""
        return Path(self.input_filename).stem
    
    @property
    def has_figures(self) -> bool:
        """Check if document has figures."""
        return len(self.figures) > 0
    
    @property
    def has_tables(self) -> bool:
        """Check if document has tables."""
        return len(self.tables) > 0
    
    @property
    def has_headers(self) -> bool:
        """Check if document has headers."""
        return len(self.headers) > 0
    
    def get_figures_by_section(self, section_ref: str) -> List[ImageNote]:
        """Get figures for a specific section."""
        return [f for f in self.figures if f.section_ref == section_ref]
    
    def get_tables_by_section(self, section_ref: str) -> List[TableNote]:
        """Get tables for a specific section."""
        return [t for t in self.tables if t.section_ref == section_ref]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'input_path': self.input_path,
            'input_filename': self.input_filename,
            'pdf_stem': self.pdf_stem,
            'markdown_path': self.markdown_path,
            'figures_dir': self.figures_dir,
            'figures': [f.to_dict() for f in self.figures],
            'tables': [t.to_dict() for t in self.tables],
            'headers': [
                {
                    'page': h.page,
                    'y_position': h.y_position,
                    'level': h.level,
                    'title': h.title,
                    'reference': h.reference,
                }
                for h in self.headers
            ],
            'metadata': self.metadata.to_dict(),
            'has_figures': self.has_figures,
            'has_tables': self.has_tables,
            'has_headers': self.has_headers,
        }
