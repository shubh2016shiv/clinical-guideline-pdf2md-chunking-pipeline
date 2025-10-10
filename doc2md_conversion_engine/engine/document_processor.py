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
        
        # Initialize AI analyzer if Gemini is enabled
        if self.config.enable_gemini:
            self.logger.info(f"Initializing AI analyzer (Gemini enabled, API key present: {bool(self.config.gemini_api_key)})")
            self.logger.debug(f"Gemini configuration: model={self.config.gemini_model_name}, temperature={self.config.gemini_temperature}")
            try:
                self.ai_analyzer = AIDocumentAnalyzer(self.config)
                self.logger.info("AI analyzer initialized successfully")
            except Exception as e:
                self.logger.error(f"Failed to initialize AI analyzer: {str(e)}")
                self.ai_analyzer = None
        else:
            self.logger.warning("Gemini disabled - AI analyzer will not be initialized")
            self.ai_analyzer = None
            
        self.markdown_builder = MarkdownBuilder(self.config)

        self.logger.info(f"DocumentProcessor initialized successfully (AI analyzer: {self.ai_analyzer is not None})")

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
            self.logger.info(f"AI Analyzer status: {self.ai_analyzer is not None}, Gemini enabled: {self.config.enable_gemini}")
            
            if extracted_content.figures:
                self.logger.info(f"Found {len(extracted_content.figures)} figures to potentially analyze")
                
                if self.ai_analyzer:
                    self.logger.info("Starting AI analysis for figure summarization")
                    try:
                        extracted_content = self.ai_analyzer.analyze(extracted_content)
                        self.logger.info("AI analysis completed successfully")
                    except Exception as e:
                        self.logger.error(f"AI analysis failed: {str(e)}")
                        self.logger.warning("Continuing with processing despite AI analysis failure")
                else:
                    self.logger.warning("AI analyzer not available - figures will not be summarized")
            else:
                self.logger.info("No figures found in document - skipping AI analysis")

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