#!/usr/bin/env python3
"""Configuration model for the guideline processor module."""

import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime
from pathvalidate import sanitize_filename

from ..exceptions import ConfigurationError, MissingConfigurationError, InvalidConfigurationError


@dataclass
class DocumentProcessingConfig:
    """
    Configuration class for the guideline processor.
    
    This class provides a centralized configuration management system
    with environment variable support, validation, and sensible defaults.
    """
    
    # I/O Configuration
    output_dir: str = field(default_factory=lambda: os.getenv("OUTPUT_DIR", "out"))
    tables_subdir: str = field(default_factory=lambda: os.getenv("TABLES_SUBDIR", "tables"))
    figures_subdir: str = field(default_factory=lambda: os.getenv("FIGURES_SUBDIR", "figures"))
    markdown_subdir: str = field(default_factory=lambda: os.getenv("MARKDOWN_SUBDIR", "markdown_file"))
    enable_datetime_subdir: bool = field(default_factory=lambda: 
        os.getenv("ENABLE_DATETIME_SUBDIR", "true").lower() == "true")
    
    # Runtime values - not configurable via environment
    _timestamp: Optional[str] = None
    
    # Document Processing
    extract_tables: bool = field(default_factory=lambda: 
        os.getenv("EXTRACT_TABLES", "false").lower() == "true")
    write_table_csv: bool = field(default_factory=lambda: 
        os.getenv("WRITE_TABLE_CSV", "false").lower() == "true")
    save_figures: bool = field(default_factory=lambda: 
        os.getenv("SAVE_FIGURES", "true").lower() == "true")
    
    # Image Processing
    image_format: str = field(default_factory=lambda: 
        os.getenv("IMAGE_FORMAT", "PNG").upper())
    image_dpi: int = field(default_factory=lambda: 
        int(os.getenv("IMAGE_DPI", "350")))
    show_image_path_in_md: bool = field(default_factory=lambda: 
        os.getenv("SHOW_IMAGE_PATH_IN_MD", "false").lower() == "true")
    
    # Docling Configuration
    docling_images_scale: float = field(default_factory=lambda: 
        float(os.getenv("DOCLING_IMAGES_SCALE", "2.0")))
    docling_generate_pictures: bool = field(default_factory=lambda: 
        os.getenv("DOCLING_GENERATE_PICTURES", "true").lower() == "true")
    
    # OCR Configuration
    ocr_lang: str = field(default_factory=lambda: 
        os.getenv("OCR_LANG", "eng"))
    
    # Gemini Configuration
    enable_gemini: bool = field(default_factory=lambda: 
        os.getenv("ENABLE_GEMINI", "false").lower() == "true")
    gemini_api_key: Optional[str] = field(default_factory=lambda: 
        os.getenv("GEMINI_API_KEY"))
    gemini_model_name: str = field(default_factory=lambda: 
        os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash"))
    
    # Processing Configuration
    max_image_workers: int = field(default_factory=lambda: 
        int(os.getenv("MAX_IMAGE_WORKERS", "3")))
    enable_progress: bool = field(default_factory=lambda: 
        os.getenv("ENABLE_PROGRESS", "true").lower() == "true")
    
    # Logging Configuration
    log_level: str = field(default_factory=lambda: 
        os.getenv("LOG_LEVEL", "INFO"))
    
    # Advanced Configuration
    strict_grounding: bool = field(default_factory=lambda: 
        os.getenv("STRICT_GROUNDING", "true").lower() == "true")
    gemini_temperature: float = field(default_factory=lambda: 
        float(os.getenv("GEMINI_TEMPERATURE", "0.1")))
    local_text_top_expand: float = field(default_factory=lambda: 
        float(os.getenv("LOCAL_TEXT_TOP_EXPAND", "80")))
    local_text_bottom_expand: float = field(default_factory=lambda: 
        float(os.getenv("LOCAL_TEXT_BOTTOM_EXPAND", "120")))
    min_ocr_chars: int = field(default_factory=lambda: 
        int(os.getenv("MIN_OCR_CHARS", "24")))
    
    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        self._validate_config()
        self._normalize_paths()
        
        # Initialize timestamp if datetime subdirectories are enabled
        if self.enable_datetime_subdir:
            self._timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    def _validate_config(self) -> None:
        """Validate configuration values."""
        # Validate numeric ranges
        if self.image_dpi <= 0:
            raise InvalidConfigurationError(
                "image_dpi", 
                self.image_dpi, 
                "positive integer"
            )
        
        if self.max_image_workers <= 0:
            raise InvalidConfigurationError(
                "max_image_workers", 
                self.max_image_workers, 
                "positive integer"
            )
        
        if not 0.0 <= self.gemini_temperature <= 1.0:
            raise InvalidConfigurationError(
                "gemini_temperature", 
                self.gemini_temperature, 
                "float between 0.0 and 1.0"
            )
        
        # Validate image format
        if self.image_format not in ["PNG", "JPEG", "JPG"]:
            raise InvalidConfigurationError(
                "image_format", 
                self.image_format, 
                "PNG, JPEG, or JPG"
            )
        
        # Validate Gemini configuration
        if self.enable_gemini and not self.gemini_api_key:
            raise MissingConfigurationError("gemini_api_key")
    
    def _normalize_paths(self) -> None:
        """Normalize and validate file paths."""
        self.output_dir = str(Path(self.output_dir).resolve())
        self.tables_subdir = str(Path(self.tables_subdir))
        self.figures_subdir = str(Path(self.figures_subdir))
        self.markdown_subdir = str(Path(self.markdown_subdir))
    
    def get_output_path(self, pdf_stem: str, subdir: Optional[str] = None) -> str:
        """
        Get output path for a specific PDF with sanitized stem name.
        
        Args:
            pdf_stem: PDF filename without extension
            subdir: Optional subdirectory
            
        Returns:
            Full output path with sanitized PDF stem
        """
        # Sanitize the PDF stem to ensure it's safe for directory creation
        safe_pdf_stem = self.sanitize_path_component(pdf_stem)
        base_path = Path(self.output_dir) / safe_pdf_stem
        
        # Add timestamp directory if enabled
        if self.enable_datetime_subdir and self._timestamp:
            base_path = base_path / self._timestamp
            
        if subdir:
            return str(base_path / subdir)
        return str(base_path)
    
    def sanitize_path_component(self, component: str) -> str:
        """
        Sanitize a path component to ensure it's safe for directory creation.
        
        Args:
            component: Path component string to sanitize
            
        Returns:
            Sanitized path component string
        """
        return sanitize_filename(component)
    
    def get_timestamp(self) -> Optional[str]:
        """
        Get the current timestamp for directory naming.
        
        Returns:
            Current timestamp string or None if datetime subdirectories are disabled
        """
        return self._timestamp
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            'output_dir': self.output_dir,
            'tables_subdir': self.tables_subdir,
            'figures_subdir': self.figures_subdir,
            'markdown_subdir': self.markdown_subdir,
            'enable_datetime_subdir': self.enable_datetime_subdir,
            'extract_tables': self.extract_tables,
            'write_table_csv': self.write_table_csv,
            'save_figures': self.save_figures,
            'image_format': self.image_format,
            'image_dpi': self.image_dpi,
            'show_image_path_in_md': self.show_image_path_in_md,
            'docling_images_scale': self.docling_images_scale,
            'docling_generate_pictures': self.docling_generate_pictures,
            'ocr_lang': self.ocr_lang,
            'enable_gemini': self.enable_gemini,
            'gemini_model_name': self.gemini_model_name,
            'max_image_workers': self.max_image_workers,
            'enable_progress': self.enable_progress,
            'log_level': self.log_level,
            'strict_grounding': self.strict_grounding,
            'gemini_temperature': self.gemini_temperature,
            'local_text_top_expand': self.local_text_top_expand,
            'local_text_bottom_expand': self.local_text_bottom_expand,
            'min_ocr_chars': self.min_ocr_chars,
        }
    
    @classmethod
    def from_env(cls) -> "DocumentProcessingConfig":
        """Create configuration from environment variables."""
        return cls()
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "DocumentProcessingConfig":
        """Create configuration from dictionary."""
        return cls(**config_dict)
