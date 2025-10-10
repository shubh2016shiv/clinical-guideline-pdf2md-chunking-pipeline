#!/usr/bin/env python3
"""Content extraction engine using Docling for PDF document processing."""

import logging
import os
import uuid
from bisect import bisect_right
from io import StringIO
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

# Core dependencies
import fitz  # PyMuPDF
from PIL import Image

# Docling imports
try:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling_core.types.doc.document import SectionHeaderItem, PictureItem
    DOCLING_AVAILABLE = True
except ImportError:
    # Graceful degradation if Docling not installed
    InputFormat = type("InputFormat", (), {})
    PdfPipelineOptions = type("PdfPipelineOptions", (), {})
    SectionHeaderItem = type("SectionHeaderItem", (), {})
    PictureItem = type("PictureItem", (), {})
    DOCLING_AVAILABLE = False

from ..models.config import DocumentProcessingConfig
from ..exceptions import ProcessingError, DocumentLoadError
from ..utils.progress import ProgressManager


@dataclass
class ExtractedContent:
    """Container for all extracted document content."""
    
    docling_document: Any
    base_markdown: str
    headers: List[Tuple[int, float, int, str, str]]  # (page, y_pos, level, title, ref)
    figures: List[Dict[str, Any]]
    tables: List[Dict[str, Any]]
    pdf_path: Path
    output_dir: Path
    figures_dir: Optional[Path] = None


class ContentExtractor:
    """Extracts structured content from PDF documents using Docling."""

    def __init__(self, config: DocumentProcessingConfig):
        """
        Initialize the content extraction engine.
        
        Args:
            config: Processing configuration settings
            
        Raises:
            ProcessingError: If Docling is not available
        """
        self.config = config
        self.logger = logging.getLogger(f"doc2md_conversion_engine.engine.{self.__class__.__name__}")
        self._progress_manager = ProgressManager(config.enable_progress)
        
        # Initialize Docling converter
        self._docling_converter = self._initialize_docling()
        
        # Runtime state
        # TODO: // Need to initialize using the centralized config
        self._current_pdf_path: Optional[Path] = None
        self._current_output_dir: Optional[Path] = None
        self._current_figures_dir: Optional[Path] = None

    def _initialize_docling(self) -> Optional[Any]:
        """
        Initialize Docling document converter with configuration.
        
        Returns:
            Configured DocumentConverter or None if unavailable
            
        Raises:
            ProcessingError: If Docling is required but not available
        """
        if not DOCLING_AVAILABLE:
            raise ProcessingError(
                "Docling library not available. Install with: pip install docling"
            )
        
        pipeline_options = PdfPipelineOptions()
        pipeline_options.images_scale = self.config.docling_images_scale
        pipeline_options.generate_page_images = True
        pipeline_options.generate_picture_images = self.config.docling_generate_pictures
        pipeline_options.do_ocr = False
        document_converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        
        self.logger.info("Docling converter initialized successfully")
        return document_converter

    def extract(self, pdf_path: str) -> ExtractedContent:
        """
        Extract all content from a PDF document.
        
        Args:
            pdf_path: Path to the PDF file to process
            
        Returns:
            ExtractedContent with all extracted elements
            
        Raises:
            DocumentLoadError: If PDF cannot be loaded
            ProcessingError: If extraction fails
        """
        pdf_path = Path(pdf_path)
        self.logger.info(f"Starting content extraction: {pdf_path.name}")
        
        # Setup output directories
        self._setup_output_directories(pdf_path)
        
        # Stage 1: Convert PDF with Docling
        self.logger.debug("Converting PDF with Docling")
        docling_doc, base_markdown = self._convert_with_docling(pdf_path)
        
        # Stage 2: Extract headers
        self.logger.debug("Extracting document headers")
        headers = self._extract_headers(docling_doc)
        self.logger.info(f"Extracted {len(headers)} headers")
        
        # Stage 3: Extract figures
        self.logger.debug("Extracting figures")
        figures = self._extract_figures(pdf_path, docling_doc, headers)
        self.logger.info(f"Extracted {len(figures)} figures")
        
        # Stage 4: Extract tables (if enabled)
        tables = []
        if self.config.extract_tables:
            self.logger.debug("Extracting tables")
            tables = self._extract_tables(pdf_path, headers)
            self.logger.info(f"Extracted {len(tables)} tables")
        
        return ExtractedContent(
            docling_document=docling_doc,
            base_markdown=base_markdown,
            headers=headers,
            figures=figures,
            tables=tables,
            pdf_path=pdf_path,
            output_dir=self._current_output_dir,
            figures_dir=self._current_figures_dir
        )

    def _setup_output_directories(self, pdf_path: Path) -> None:
        """
        Create necessary output directories for processing.
        
        Args:
            pdf_path: Source PDF file path
        """
        pdf_stem = pdf_path.stem
        self._current_output_dir = Path(self.config.output_dir) / pdf_stem
        self._current_output_dir.mkdir(parents=True, exist_ok=True)
        
        if self.config.save_figures:
            self._current_figures_dir = self._current_output_dir / self.config.figures_subdir
            self._current_figures_dir.mkdir(parents=True, exist_ok=True)
        
        self._current_pdf_path = pdf_path

    def _convert_with_docling(self, pdf_path: Path) -> Tuple[Any, str]:
        """
        Convert PDF to structured document using Docling.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Tuple of (Docling document object, base markdown text)
            
        Raises:
            DocumentLoadError: If conversion fails
        """
        try:
            result = self._docling_converter.convert(str(pdf_path))
            document = result.document
            markdown = document.export_to_markdown()
            self.logger.info(f"Docling conversion successful: {str(pdf_path)}")
            return document, markdown
        except Exception as e:
            raise DocumentLoadError(
                str(pdf_path),
                f"Docling conversion failed: {str(e)}"
            ) from e

    def _extract_headers(self, docling_doc: Any) -> List[Tuple[int, float, int, str, str]]:
        """
        Extract and index all section headers from document.
        
        Args:
            docling_doc: Docling document object
            
        Returns:
            List of tuples: (page_number, y_position, level, title, reference)
        """
        headers = []
        
        iterate_items = getattr(docling_doc, "iterate_items", None)
        if not callable(iterate_items):
            self.logger.warning("Document does not support item iteration")
            return headers
        
        for element, _ in docling_doc.iterate_items():
            if not isinstance(element, SectionHeaderItem):
                continue
            
            provenance = getattr(element, "prov", None)
            if not provenance:
                continue
            
            # Extract header metadata
            page_number = provenance[0].page_no
            y_position = self._get_bbox_top_y(provenance)
            level = getattr(element, "level", 1)
            title = getattr(element, "text", "") or getattr(element, "title", "") or ""
            reference = getattr(element, "self_ref", "")
            
            headers.append((page_number, y_position, level, title, reference))
        
        # Sort by page and position
        headers.sort(key=lambda h: (h[0], h[1]))
        return headers

    def _build_header_index(
        self, headers: List[Tuple[int, float, int, str, str]]
    ) -> Dict[int, List[Tuple[float, str, str]]]:
        """
        Build page-indexed header lookup structure for efficient binary search.
        
        Args:
            headers: List of extracted headers (page, y_pos, level, title, ref)
            
        Returns:
            Dictionary mapping page_number -> [(y_pos, title, ref), ...]
        """
        index: Dict[int, List[Tuple[float, str, str]]] = {}
        for page, y_pos, level, title, ref in headers:
            if page not in index:
                index[page] = []
            index[page].append((y_pos, title, ref))
        return index

    def _get_bbox_top_y(self, provenance: Any) -> float:
        """
        Extract top Y coordinate from provenance bounding box.
        
        Args:
            provenance: Docling provenance object
            
        Returns:
            Y coordinate (0.0 if unavailable)
        """
        if not provenance or not getattr(provenance[0], "bbox", None):
            return 0.0
        
        bbox = provenance[0].bbox
        return float(getattr(bbox, "t", 0.0))

    def _extract_figures(
        self,
        pdf_path: Path,
        docling_doc: Any,
        headers: List[Tuple[int, float, int, str, str]]
    ) -> List[Dict[str, Any]]:
        """
        Extract all figures/images from document with parallel processing.
        
        Args:
            pdf_path: Source PDF path
            docling_doc: Docling document object
            headers: Extracted headers for section association
            
        Returns:
            List of figure metadata dictionaries
        """
        # Count pictures for progress bar (lightweight iteration)
        picture_count = sum(1 for _ in self._iterate_pictures(docling_doc))
        if picture_count == 0:
            return []
        
        # Build header index for efficient lookups
        header_index = self._build_header_index(headers)
        
        figures = []
        progress_bar = self._progress_manager.create_progress_bar(
            total=picture_count,
            desc="Figures"
        )
        
        try:
            max_workers = max(1, self.config.max_image_workers)
            
            # Process pictures lazily without list materialization
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Create list of futures first to ensure stable collection
                futures_list = [
                    executor.submit(self._process_single_figure, pdf_path, docling_doc, pic, header_index)
                    for pic in self._iterate_pictures(docling_doc)
                ]
                
                # Track the number of processed futures
                processed_count = 0
                
                for future in as_completed(futures_list):
                    try:
                        figure_data = future.result()
                        figures.append(figure_data)
                    except Exception as e:
                        self.logger.error(f"Figure extraction failed: {str(e)}")
                    finally:
                        processed_count += 1
                        progress_bar.update(1)
                
                # Ensure progress bar is complete
                if processed_count < picture_count:
                    self.logger.warning(
                        f"Progress tracking mismatch: processed {processed_count}/{picture_count} figures"
                    )
                    # Force progress bar to completion if needed
                    progress_bar.update(picture_count - processed_count)
        finally:
            progress_bar.close()
        
        # Sort by page and figure ID
        figures.sort(key=lambda f: (f["page"], f["figure_id"]))
        return figures

    def _iterate_pictures(self, docling_doc: Any):
        """
        Iterate through all picture items in document.
        
        Args:
            docling_doc: Docling document object
            
        Yields:
            PictureItem objects
        """
        iterate_items = getattr(docling_doc, "iterate_items", None)
        if not callable(iterate_items):
            return
        
        for element, _ in docling_doc.iterate_items():
            if isinstance(element, PictureItem) and getattr(element, "prov", None):
                yield element

    def _process_single_figure(
        self,
        pdf_path: Path,
        docling_doc: Any,
        picture_item: Any,
        header_index: Dict[int, List[Tuple[float, str, str]]]
    ) -> Dict[str, Any]:
        """
        Process a single figure: extract, crop, and generate metadata.
        
        Args:
            pdf_path: Source PDF path
            docling_doc: Docling document
            picture_item: Picture element from Docling
            header_index: Page-indexed header lookup structure
            
        Returns:
            Figure metadata dictionary
        """
        page_number = picture_item.prov[0].page_no
        
        # Extract caption
        caption = self._extract_caption(picture_item, docling_doc)
        
        # Extract image
        image = self._extract_picture_image(pdf_path, docling_doc, picture_item)
        
        # Associate with nearest section using efficient lookup
        section_title, section_ref = self._find_nearest_header(
            header_index,
            picture_item.prov
        )
        
        # Generate unique ID and save
        figure_id = f"p{page_number}_f{uuid.uuid4().hex[:6]}"
        image_path = self._save_figure(image, figure_id)
        
        return {
            "page": page_number,
            "figure_id": figure_id,
            "caption": caption,
            "section_anchor": section_title or "",
            "section_ref": section_ref or "",
            "image_path": image_path,
            "image": image  # Keep for AI analysis
        }

    def _extract_caption(self, picture_item: Any, docling_doc: Any) -> str:
        """
        Extract caption text from picture item.
        
        Args:
            picture_item: Docling picture element
            docling_doc: Parent document
            
        Returns:
            Caption text (empty string if unavailable)
        """
        caption = getattr(picture_item, "caption", None) or getattr(picture_item, "caption_text", None)
        
        if callable(caption):
            try:
                caption = caption(docling_doc)
            except Exception:
                caption = ""
        
        return str(caption or "")

    def _extract_picture_image(
        self,
        pdf_path: Path,
        docling_doc: Any,
        picture_item: Any
    ) -> Optional[Image.Image]:
        """
        Extract picture as PIL Image, with fallback to PyMuPDF.
        
        Args:
            pdf_path: Source PDF path
            docling_doc: Docling document
            picture_item: Picture element
            
        Returns:
            PIL Image or None if extraction fails
        """
        # Try Docling's built-in image extraction first
        get_image = getattr(picture_item, "get_image", None)
        if callable(get_image):
            try:
                return get_image(docling_doc)
            except Exception as e:
                self.logger.debug(f"Docling image extraction failed: {e}")
        
        # Fallback to PyMuPDF cropping
        return self._extract_image_with_pymupdf(pdf_path, picture_item)

    def _extract_image_with_pymupdf(
        self,
        pdf_path: Path,
        picture_item: Any
    ) -> Optional[Image.Image]:
        """
        Extract image using PyMuPDF as fallback.
        
        Args:
            pdf_path: Source PDF path
            picture_item: Picture element with provenance
            
        Returns:
            PIL Image or None if extraction fails
        """
        try:
            page_number = picture_item.prov[0].page_no
            
            with fitz.open(str(pdf_path)) as pdf_doc:
                page = pdf_doc.load_page(page_number - 1)  # 0-indexed
                rect = self._convert_bbox_to_rect(page, picture_item.prov)
                
                pixmap = page.get_pixmap(
                    dpi=self.config.image_dpi,
                    clip=rect,
                    alpha=False
                )
                
                if pixmap.width <= 1 or pixmap.height <= 1:
                    return None
                
                return Image.frombytes(
                    "RGB",
                    [pixmap.width, pixmap.height],
                    pixmap.samples
                )
        except Exception as e:
            self.logger.warning(f"PyMuPDF image extraction failed: {e}")
            return None

    def _convert_bbox_to_rect(self, page: fitz.Page, provenance: Any) -> fitz.Rect:
        """
        Convert Docling bounding box to PyMuPDF rectangle.
        
        Args:
            page: PyMuPDF page object
            provenance: Docling provenance with bbox
            
        Returns:
            PyMuPDF Rect object
        """
        bbox = provenance[0].bbox
        left = float(getattr(bbox, "l", 0.0))
        right = float(getattr(bbox, "r", 0.0))
        top = float(getattr(bbox, "t", 0.0))
        bottom = float(getattr(bbox, "b", 0.0))
        
        page_height = float(page.rect.height)
        coord_origin = getattr(getattr(bbox, "coord_origin", None), "name", "TOP_LEFT")
        
        # Handle coordinate system conversion
        if coord_origin == "BOTTOM_LEFT":
            top_tl = page_height - top
            bottom_tl = page_height - bottom
            y0, y1 = min(top_tl, bottom_tl), max(top_tl, bottom_tl)
        else:
            y0, y1 = min(top, bottom), max(top, bottom)
        
        x0, x1 = min(left, right), max(left, right)
        
        # Create rectangle with page bounds
        rect = fitz.Rect(x0, y0, x1, y1) & page.rect
        
        # Add padding if rectangle is too small
        if rect.width <= 1 or rect.height <= 1:
            padding = 2
            rect = fitz.Rect(
                max(0, x0 - padding),
                max(0, y0 - padding),
                min(page.rect.width, x1 + padding),
                min(page.rect.height, y1 + padding)
            ) & page.rect
        
        return rect

    def _save_figure(
        self,
        image: Optional[Image.Image],
        figure_id: str
    ) -> Optional[str]:
        """
        Save figure image to disk.
        
        Args:
            image: PIL Image to save
            figure_id: Unique figure identifier
            
        Returns:
            Path to saved image or None if not saved
        """
        if not self.config.save_figures or not image or not self._current_figures_dir:
            return None
        
        try:
            extension = "png" if self.config.image_format.upper() == "PNG" else "jpg"
            output_path = self._current_figures_dir / f"{figure_id}.{extension}"
            
            # Convert to RGB for JPEG if needed
            if self.config.image_format.upper() == "JPEG" and image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            
            image.save(output_path, format=self.config.image_format.upper())
            return str(output_path)
            
        except Exception as e:
            self.logger.warning(f"Failed to save figure {figure_id}: {e}")
            return None

    def _find_nearest_header(
        self,
        header_index: Dict[int, List[Tuple[float, str, str]]],
        provenance: Any
    ) -> Tuple[str, str]:
        """
        Find the nearest preceding header using page-indexed binary search.
        
        Args:
            header_index: Page-indexed header lookup structure
            provenance: Element provenance with position
            
        Returns:
            Tuple of (header_title, header_reference)
        """
        if not provenance or not header_index:
            return "", ""
        
        page_number = provenance[0].page_no
        y_position = self._get_bbox_top_y(provenance)
        
        # Check same page with binary search
        if page_number in header_index:
            page_headers = header_index[page_number]
            idx = bisect_right([h[0] for h in page_headers], y_position)
            if idx > 0:
                return page_headers[idx - 1][1], page_headers[idx - 1][2]
        
        # Check previous pages in reverse order
        for prev_page in range(page_number - 1, 0, -1):
            if prev_page in header_index:
                last_header = header_index[prev_page][-1]
                return last_header[1], last_header[2]
        
        return "", ""

    def _extract_tables(
        self,
        pdf_path: Path,
        headers: List[Tuple[int, float, int, str, str]]
    ) -> List[Dict[str, Any]]:
        """
        Extract tables from PDF using pdfplumber.
        
        Args:
            pdf_path: Source PDF path
            headers: Document headers for section association
            
        Returns:
            List of table metadata dictionaries
        """
        try:
            import pdfplumber
        except ImportError:
            self.logger.warning("pdfplumber not available. Skipping table extraction.")
            return []
        
        # Build header index for efficient lookups
        header_index = self._build_header_index(headers)
        
        tables = []
        tables_dir = self._current_output_dir / self.config.tables_subdir
        
        if self.config.write_table_csv:
            tables_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_idx, page in enumerate(pdf.pages):
                    page_number = page_idx + 1
                    
                    try:
                        extracted_tables = page.extract_tables()
                    except Exception as e:
                        self.logger.debug(f"Table extraction failed on page {page_number}: {e}")
                        continue
                    
                    if not extracted_tables:
                        continue
                    
                    for table_idx, table_data in enumerate(extracted_tables, start=1):
                        table_id = f"p{page_number}_t{table_idx}"
                        markdown = self._convert_table_to_markdown(table_data)
                        
                        # Save CSV if enabled
                        csv_path = None
                        if self.config.write_table_csv:
                            csv_path = self._save_table_csv(table_data, table_id, tables_dir)
                        
                        # Find nearest section using efficient lookup
                        section_title, section_ref = self._find_nearest_header_by_page(
                            header_index,
                            page_number
                        )
                        
                        tables.append({
                            "page": page_number,
                            "table_id": table_id,
                            "md": markdown,
                            "csv_path": csv_path,
                            "section_anchor": section_title or "",
                            "section_ref": section_ref or ""
                        })
        
        except Exception as e:
            self.logger.error(f"Table extraction failed: {e}")
        
        return tables

    def _convert_table_to_markdown(self, table_data: List[List[str]]) -> str:
        """
        Convert table data to markdown format using efficient string buffer.
        
        Args:
            table_data: 2D list of table cells
            
        Returns:
            Markdown formatted table
        """
        if not table_data:
            return ""
        
        def escape_cell(cell: Optional[str]) -> str:
            """Escape pipe characters in cell content."""
            return (cell or "").replace("|", r"\|").strip()
        
        buffer = StringIO()
        
        # Header row
        buffer.write("|")
        buffer.write("|".join(escape_cell(cell) for cell in table_data[0]))
        buffer.write("|\n")
        
        # Separator row
        buffer.write("|")
        buffer.write("|".join(["---"] * len(table_data[0])))
        buffer.write("|\n")
        
        # Data rows
        for row in table_data[1:]:
            buffer.write("|")
            buffer.write("|".join(escape_cell(cell) for cell in row))
            buffer.write("|\n")
        
        return buffer.getvalue()

    def _save_table_csv(
        self,
        table_data: List[List[str]],
        table_id: str,
        tables_dir: Path
    ) -> Optional[str]:
        """
        Save table data as CSV file.
        
        Args:
            table_data: 2D list of table cells
            table_id: Unique table identifier
            tables_dir: Directory for table files
            
        Returns:
            Path to saved CSV or None if failed
        """
        try:
            csv_path = tables_dir / f"{table_id}.csv"
            
            with open(csv_path, "w", encoding="utf-8") as f:
                for row in table_data:
                    # Escape quotes in cells
                    escaped_row = [
                        f'"{(cell or "").replace(chr(34), chr(34) + chr(34))}"'
                        for cell in row
                    ]
                    f.write(",".join(escaped_row) + "\n")
            
            return str(csv_path)
            
        except Exception as e:
            self.logger.warning(f"Failed to save table CSV {table_id}: {e}")
            return None

    def _find_nearest_header_by_page(
        self,
        header_index: Dict[int, List[Tuple[float, str, str]]],
        page_number: int
    ) -> Tuple[str, str]:
        """
        Find the nearest header for a given page using indexed lookup.
        
        Args:
            header_index: Page-indexed header lookup structure
            page_number: Page number to find header for
            
        Returns:
            Tuple of (header_title, header_reference)
        """
        if not header_index:
            return "", ""
        
        # Check current page first
        if page_number in header_index:
            last_header = header_index[page_number][-1]
            return last_header[1], last_header[2]
        
        # Check previous pages in reverse order
        for prev_page in range(page_number - 1, 0, -1):
            if prev_page in header_index:
                last_header = header_index[prev_page][-1]
                return last_header[1], last_header[2]
        
        return "", ""
