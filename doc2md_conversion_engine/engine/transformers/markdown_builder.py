#!/usr/bin/env python3
"""
Markdown builder module for transforming extracted document content into structured markdown output.

This module provides the MarkdownBuilder class which is responsible for organizing
document content into a hierarchical structure and generating well-formatted markdown
with integrated figures and tables.
"""

import logging
import os
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Set

from ...models.config import DocumentProcessingConfig
from ...models.document import DocumentResult, HeaderInfo, ImageNote, TableNote
from ...exceptions import OutputError
from ..content_extractor import ExtractedContent


class MarkdownBuilder:
    """
    Transforms extracted document content into structured markdown output.
    
    This class is responsible for:
    1. Building a structured markdown document from extracted content
    2. Organizing content by sections with proper hierarchy
    3. Integrating figures and tables into their respective sections
    4. Generating consistent output formatting
    
    Attributes:
        config: Configuration settings for document processing
        logger: Logger instance for this class
    """
    
    def __init__(self, config: DocumentProcessingConfig):
        """
        Initialize the markdown builder with configuration settings.
        
        Args:
            config: Configuration settings for document processing
            
        Raises:
            ValueError: If configuration is invalid
        """
        self.config = config
        self.logger = logging.getLogger(f"doc_engine.{self.__class__.__name__}")
        
        # Validate critical configuration
        if not config.output_dir:
            raise ValueError("Output directory must be specified in configuration")
    
    def generate(
        self,
        content: ExtractedContent,
        output_path: Optional[str] = None,
        output_filename: Optional[str] = None
    ) -> DocumentResult:
        """
        Generate structured markdown from extracted document content.
        
        Args:
            content: Extracted document content including base markdown, headers, figures, and tables
            output_path: Optional custom output directory path (overrides config)
            output_filename: Optional custom output filename without extension
            
        Returns:
            DocumentResult containing the processing results and metadata
            
        Raises:
            OutputError: If output generation fails
            ValueError: If content is invalid
        """
        if not content or not content.base_markdown:
            raise ValueError("Content must contain base markdown text")
        
        self.logger.info("Generating structured markdown output")
        
        try:
            # Setup output paths
            output_info = self._setup_output_paths(content, output_path, output_filename)
            
            # Create document result object
            document_result = DocumentResult(
                input_path=str(content.pdf_path),
                input_filename=content.pdf_path.name,
                markdown_path=output_info["markdown_path"],
                figures_dir=output_info.get("figures_dir")
            )
            
            # Convert raw content to typed objects
            headers = self._convert_headers(content.headers)
            figures = self._convert_figures(content.figures)
            tables = self._convert_tables(content.tables)
            
            # Update document result with content
            document_result.headers = headers
            document_result.figures = figures
            document_result.tables = tables
            document_result.raw_markdown = content.base_markdown
            document_result.docling_document = content.docling_document
            
            # Organize content by sections
            self.logger.debug("Organizing content by sections")
            final_markdown = self._organize_content_by_sections(
                content.base_markdown,
                headers,
                figures,
                tables
            )
            
            # Write markdown to file
            self.logger.debug(f"Writing markdown to {output_info['markdown_path']}")
            with open(output_info["markdown_path"], "w", encoding="utf-8") as f:
                f.write(final_markdown)
            
            # Update metadata
            document_result.metadata.add_stage("markdown_generation")
            document_result.metadata.complete()
            
            self.logger.info(f"Markdown generation completed: {output_info['markdown_path']}")
            return document_result
            
        except Exception as e:
            self.logger.exception("Failed to generate markdown output")
            raise OutputError(f"Markdown generation failed: {str(e)}") from e
    
    def _setup_output_paths(
        self,
        content: ExtractedContent,
        output_path: Optional[str],
        output_filename: Optional[str]
    ) -> Dict[str, str]:
        """
        Setup output directory structure and paths.
        
        Args:
            content: Extracted document content
            output_path: Optional custom output directory
            output_filename: Optional custom output filename
            
        Returns:
            Dictionary with output path information
            
        Raises:
            OutputError: If directory creation fails
        """
        pdf_stem = content.pdf_path.stem
        
        # Determine base output directory
        if output_path:
            base_dir = Path(output_path)
        else:
            # Use the get_output_path method which handles timestamp subdirectory if enabled
            base_dir = Path(self.config.get_output_path(pdf_stem))
        
        # Add markdown subdirectory
        markdown_dir = base_dir / self.config.markdown_subdir
        
        # Ensure directories exist
        try:
            markdown_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise OutputError(f"Failed to create output directory: {str(e)}") from e
        
        # Determine markdown filename
        if output_filename:
            md_filename = f"{output_filename}.md"
        else:
            md_filename = "output.md"
        
        # Full markdown path
        markdown_path = markdown_dir / md_filename
        
        # Return paths dictionary
        result = {
            "base_dir": str(base_dir),
            "markdown_dir": str(markdown_dir),
            "markdown_path": str(markdown_path),
        }
        
        # Include figures directory if available
        if content.figures_dir:
            result["figures_dir"] = str(content.figures_dir)
        
        return result
    
    def _convert_headers(
        self, 
        headers: List[Tuple[int, float, int, str, str]]
    ) -> List[HeaderInfo]:
        """
        Convert raw header tuples to HeaderInfo objects.
        
        Args:
            headers: List of header tuples (page, y_pos, level, title, ref)
            
        Returns:
            List of HeaderInfo objects
        """
        result = []
        for page, y_pos, level, title, ref in headers:
            try:
                header_info = HeaderInfo(
                    page=page,
                    y_position=y_pos,
                    level=level,
                    title=title,
                    reference=ref
                )
                result.append(header_info)
            except ValueError as e:
                self.logger.warning(f"Skipping invalid header: {str(e)}")
        return result
    
    def _convert_figures(self, figures: List[Dict[str, Any]]) -> List[ImageNote]:
        """
        Convert raw figure dictionaries to ImageNote objects.
        
        Args:
            figures: List of figure dictionaries
            
        Returns:
            List of ImageNote objects
        """
        result = []
        for fig in figures:
            try:
                # Extract summary from figure if available
                summary = fig.get("summary", "")
                if not summary and "image" in fig:
                    # This would be populated by AI analyzer in a real implementation
                    summary = "Figure detected (no summary available)"
                
                image_note = ImageNote(
                    page=fig["page"],
                    figure_id=fig["figure_id"],
                    caption=fig.get("caption", ""),
                    summary=summary,
                    section_anchor=fig.get("section_anchor", ""),
                    section_ref=fig.get("section_ref", ""),
                    image_path=fig.get("image_path")
                )
                result.append(image_note)
            except (ValueError, KeyError) as e:
                self.logger.warning(f"Skipping invalid figure: {str(e)}")
        return result
    
    def _convert_tables(self, tables: List[Dict[str, Any]]) -> List[TableNote]:
        """
        Convert raw table dictionaries to TableNote objects.
        
        Args:
            tables: List of table dictionaries
            
        Returns:
            List of TableNote objects
        """
        result = []
        for tab in tables:
            try:
                table_note = TableNote(
                    page=tab["page"],
                    table_id=tab["table_id"],
                    markdown=tab["md"],
                    csv_path=tab.get("csv_path"),
                    section_anchor=tab.get("section_anchor", ""),
                    section_ref=tab.get("section_ref", "")
                )
                result.append(table_note)
            except (ValueError, KeyError) as e:
                self.logger.warning(f"Skipping invalid table: {str(e)}")
        return result
    
    def _organize_content_by_sections(
        self,
        base_markdown: str,
        headers: List[HeaderInfo],
        figures: List[ImageNote],
        tables: List[TableNote]
    ) -> str:
        """
        Parse markdown into sections and associate content with each section.
        
        Args:
            base_markdown: Base markdown text from document conversion
            headers: List of document headers
            figures: List of extracted figures
            tables: List of extracted tables
            
        Returns:
            Structured markdown with integrated figures and tables
        """
        # Parse markdown into sections
        sections = self._parse_sections(base_markdown)
        
        # Create lookup dictionaries for section references
        section_refs = {}
        section_titles = {}
        
        for header in headers:
            if header.reference:
                section_refs[header.reference] = []
            if header.title:
                section_titles[header.title] = []
        
        # Associate figures with sections
        for figure in figures:
            if figure.section_ref and figure.section_ref in section_refs:
                section_refs[figure.section_ref].append(
                    self._generate_figure_block(figure)
                )
            elif figure.section_anchor and figure.section_anchor in section_titles:
                section_titles[figure.section_anchor].append(
                    self._generate_figure_block(figure)
                )
            else:
                # Default section for unassociated figures
                section_refs.setdefault("", []).append(
                    self._generate_figure_block(figure)
                )
        
        # Associate tables with sections
        for table in tables:
            if table.section_ref and table.section_ref in section_refs:
                section_refs[table.section_ref].append(
                    self._generate_table_block(table)
                )
            elif table.section_anchor and table.section_anchor in section_titles:
                section_titles[table.section_anchor].append(
                    self._generate_table_block(table)
                )
            else:
                # Default section for unassociated tables
                section_refs.setdefault("", []).append(
                    self._generate_table_block(table)
                )
        
        # Build final markdown by injecting content into sections
        output_lines = []
        for section in sections:
            # Add section content
            output_lines.extend(section["content"])
            output_lines.append("")
            
            # Add associated assets
            section_ref = section.get("ref", "")
            section_title = section.get("title", "")
            
            assets = []
            assets.extend(section_refs.get(section_ref, []))
            assets.extend(section_titles.get(section_title, []))
            
            if assets:
                # Add asset separator and header
                output_lines.append("> ---")
                
                asset_types = []
                if any(a.startswith("> **Figure") for a in assets):
                    asset_types.append("figures")
                if any(a.startswith("> **Table") for a in assets):
                    asset_types.append("tables")
                
                asset_type_text = "/".join(asset_types)
                output_lines.append(f"> **Auto-extracted {asset_type_text}**")
                output_lines.append("> ---\n")
                
                # Add assets
                output_lines.extend(assets)
        
        # Handle unassociated assets
        if "" in section_refs and section_refs[""]:
            output_lines.append("\n## Unassociated Content\n")
            output_lines.append("> ---")
            output_lines.append("> **Auto-extracted content without section association**")
            output_lines.append("> ---\n")
            output_lines.extend(section_refs[""])
        
        return "\n".join(output_lines).rstrip() + "\n"
    
    def _parse_sections(self, markdown_text: str) -> List[Dict[str, Any]]:
        """
        Parse markdown text into a list of sections.
        
        Args:
            markdown_text: Raw markdown text
            
        Returns:
            List of section dictionaries with level, title, content, and ref
        """
        lines = markdown_text.splitlines()
        sections = []
        current_section = None
        
        # Regular expression for markdown headers
        header_pattern = re.compile(r"^(#+)\s+(.*)$")
        
        # Dictionary to track section references by title
        section_refs: Dict[str, str] = {}
        
        # First pass: extract section references from headers
        for line in lines:
            match = header_pattern.match(line)
            if match:
                level = len(match.group(1))
                title = match.group(2).strip()
                # In a real implementation, we would extract references from headers
                # For now, we'll use an empty string as a placeholder
                section_refs[title] = ""
        
        # Second pass: build sections
        for line in lines:
            match = header_pattern.match(line)
            if match:
                # If we have a current section, add it to the list
                if current_section:
                    sections.append(current_section)
                
                # Create a new section
                level = len(match.group(1))
                title = match.group(2).strip()
                current_section = {
                    "level": level,
                    "title": title,
                    "content": [line],
                    "ref": section_refs.get(title, "")
                }
            else:
                # Add line to current section
                if current_section is None:
                    # Create a default section if we start with content
                    current_section = {
                        "level": 1,
                        "title": "Document",
                        "content": [],
                        "ref": ""
                    }
                current_section["content"].append(line)
        
        # Add the last section
        if current_section:
            sections.append(current_section)
        
        return sections
    
    def _generate_figure_block(self, figure: ImageNote) -> str:
        """
        Format figure metadata as a markdown block.
        
        Args:
            figure: Figure information
            
        Returns:
            Formatted markdown block for the figure
        """
        # Header with figure ID and page number
        header = f"> **Figure (p.{figure.page})** `{figure.figure_id}`"
        
        # Caption (if available)
        caption_line = None
        if figure.caption:
            caption_line = f"> _Caption_: {figure.caption}"
        
        # Summary with indented bullet points
        summary = f"> _Summary_:\n{self._indent_bullet_points(figure.summary)}"
        
        # Image path (if configured to show)
        image_line = None
        if self.config.show_image_path_in_md and figure.image_path:
            image_line = f"> _Image_: `{figure.image_path}`"
        
        # Build the complete block
        parts = [header]
        if image_line:
            parts.append(image_line)
        if caption_line:
            parts.append(caption_line)
        parts.append(summary)
        parts.append("")  # Empty line at the end
        
        return "\n".join(parts)
    
    def _generate_table_block(self, table: TableNote) -> str:
        """
        Format table metadata as a markdown block.
        
        Args:
            table: Table information
            
        Returns:
            Formatted markdown block for the table
        """
        # Header with table ID and page number
        header = f"> **Table (p.{table.page})** `{table.table_id}`"
        
        # CSV path (if available)
        csv_line = None
        if table.csv_path:
            csv_line = f"> _CSV_: `{table.csv_path}`"
        
        # Build the complete block
        parts = [header]
        if csv_line:
            parts.append(csv_line)
        parts.append(table.markdown)
        parts.append("")  # Empty line at the end
        
        return "\n".join(parts)
    
    def _indent_bullet_points(self, text: str) -> str:
        """
        Format bullet points with proper indentation.
        
        Args:
            text: Text containing bullet points
            
        Returns:
            Text with properly indented bullet points
        """
        lines = []
        for line in (text or "").splitlines():
            if line.strip().startswith("- "):
                lines.append("> " + line.strip())
            else:
                lines.append("> " + line)
        return "\n".join(lines)
