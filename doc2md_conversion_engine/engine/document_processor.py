#!/usr/bin/env python3
"""Core document processing engine for converting PDFs to structured outputs."""

import logging
from pathlib import Path
from typing import Optional

from .content_extractor import ContentExtractor
from doc2md_conversion_engine.engine.figure_summarization_agent.agent import AIDocumentAnalyzer
from .transformers.markdown_builder import MarkdownBuilder
from ..models import DocumentProcessingConfig, DocumentResult
from ..exceptions import (
    ConfigurationError,
    ProcessingError,
    DocumentLoadError,
    OutputError
)


class DocumentProcessor:
    """Main engine for processing documents through extraction, analysis, and transformation pipelines."""

    def __init__(self, config: Optional[DocumentProcessingConfig] = None):
        """
        Initialize the document processing engine.

        Args:
            config: Configuration settings. Uses defaults if not provided.

        Raises:
            ConfigurationError: For invalid configuration parameters
        """
        self.config = config or DocumentProcessingConfig()
        self._validate_config()
        self._setup_logging()

        # Initialize processing components
        self.content_extractor = ContentExtractor(self.config)
        self.ai_analyzer = AIDocumentAnalyzer(self.config) if self.config.enable_gemini else None
        self.markdown_builder = MarkdownBuilder(self.config)

        self.logger.info("DocumentProcessor initialized successfully")

    def _validate_config(self) -> None:
        """Validate critical configuration parameters."""
        if not self.config.output_dir:
            raise ConfigurationError("Output directory must be specified")

        if self.config.image_format not in {"PNG", "JPEG", "JPG"}:
            raise ConfigurationError(
                f"Invalid image format '{self.config.image_format}'. "
                "Valid options: PNG, JPEG, JPG"
            )

    def _setup_logging(self) -> None:
        """Configure logging according to specification."""
        self.logger = logging.getLogger(f"doc2md_conversion_engine.engine.document_processor.{self.__class__.__name__}")
        self.logger.setLevel(self.config.log_level.upper())

        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def process_document(
            self,
            pdf_path: str,
            *,
            output_path: Optional[str] = None,
            output_filename: Optional[str] = None
    ) -> DocumentResult:
        """
        Execute full document processing pipeline for a PDF file.

        Args:
            pdf_path: Path to source PDF document
            output_path: Custom output directory (overrides config)
            output_filename: Custom output filename without extension

        Returns:
            DocumentResult containing processing artifacts and metadata

        Raises:
            DocumentLoadError: If PDF cannot be loaded or is invalid
            ProcessingError: For failures during content processing
            OutputError: If results cannot be persisted
        """
        self.logger.info(f"Starting processing: {Path(pdf_path).name}")

        try:
            # Stage 1: Content extraction
            self.logger.debug("Extracting document content")
            extracted_content = self.content_extractor.extract(pdf_path)

            # Stage 2: AI analysis (conditional)
            if self.ai_analyzer:
                self.logger.debug("Performing AI analysis")
                extracted_content = self.ai_analyzer.analyze(extracted_content)

            # Stage 3: Output generation
            self.logger.debug("Building output structure")
            result = self.markdown_builder.generate(
                extracted_content,
                output_path=output_path,
                output_filename=output_filename
            )

            self.logger.info(
                f"Processing completed successfully. Output: {result.markdown_path}"
            )
            return result

        except DocumentLoadError as e:
            self.logger.error(f"Document loading failed: {str(e)}")
            raise
        except OutputError as e:
            self.logger.error(f"Output generation failed: {str(e)}")
            raise
        except Exception as e:
            self.logger.exception("Unexpected processing error")
            raise ProcessingError(f"Processing failure: {str(e)}") from e

    def shutdown(self) -> None:
        """Clean up processor resources and connections."""
        self.logger.info("Shutting down DocumentProcessor")
        if self.ai_analyzer:
            self.ai_analyzer.cleanup()