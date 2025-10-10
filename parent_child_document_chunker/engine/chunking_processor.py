#!/usr/bin/env python3
"""Main processor class for document chunking operations."""

import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any, Union
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..schema.configuration import ChunkingConfig
from ..schema.document_chunks import ChunkedDocument, ChunkMetadata, Document
from ..exceptions import ChunkingError, FileError, ValidationError
from ..utilities.file_operations import validate_markdown_file, ensure_directory, get_output_path
from ..utilities.progress_tracking import ProgressManager
from .markdown_parser import StructureAwareChunker


class DocumentChunker:
    """
    Main processor class for chunking markdown documents.
    
    This class orchestrates the entire chunking pipeline, from markdown input
    to structured parent/child chunks with comprehensive metadata.
    """
    
    def __init__(self, config: Optional[ChunkingConfig] = None):
        """
        Initialize the document chunker.
        
        Args:
            config: Configuration object. If None, uses default configuration.
        """
        self.config = config or ChunkingConfig()
        self._validate_config()
        
        # Initialize components
        self._progress_manager = ProgressManager(self.config.enable_progress)
        self._chunker = StructureAwareChunker(
            child_token_limit=self.config.child_token_limit,
            child_overlap_tokens=self.config.child_overlap_tokens,
            min_chunk_tokens=self.config.min_chunk_tokens,
            progress_manager=self._progress_manager
        )
        
        # Setup logging
        self._setup_logging()
        
        self.logger.info("DocumentChunker initialized successfully")
    
    def _validate_config(self) -> None:
        """Validate configuration."""
        try:
            # Config validation is handled in __post_init__
            pass
        except Exception as e:
            raise ValidationError(
                f"Invalid configuration: {e}",
                field="config",
                value=str(self.config)
            )
    
    def _setup_logging(self) -> None:
        """Setup logging configuration."""
        self.logger = logging.getLogger(f"{__name__}.{id(self)}")
        
        # Set log level
        log_level = getattr(logging, "INFO", logging.INFO)
        self.logger.setLevel(log_level)
        
        # Add handler if none exists
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
    
    def chunk_file(
        self, 
        file_path: Union[str, Path],
        *,
        output_path: Optional[Union[str, Path]] = None,
        output_filename: Optional[str] = None
    ) -> ChunkedDocument:
        """
        Chunk a markdown file.
        
        Args:
            file_path: Path to the markdown file
            output_path: Custom output directory
            output_filename: Custom output filename (without extension)
            
        Returns:
            ChunkedDocument containing all chunk information
            
        Raises:
            FileError: If file operations fail
            ChunkingError: If chunking fails
        """
        try:
            # ========================================
            # STEP 1: MARKDOWN FILE INPUT PROCESSING
            # ========================================
            # Validate input file (ensures it's a valid markdown file)
            file_path = validate_markdown_file(file_path)
            self.logger.info(f"Chunking document: {file_path}")
            
            # Read markdown content from file into memory
            with open(file_path, "r", encoding="utf-8") as f:
                md_text = f.read()  # ← MARKDOWN INPUT: Raw markdown text loaded here
            
            # Extract PDF stem from path if available (for organization)
            pdf_stem = self._extract_pdf_stem(file_path)
            
            # ========================================
            # STEP 2: CORE CHUNKING LOGIC
            # ========================================
            # This is where the magic happens - the _chunker processes the markdown text
            # and returns the tuple (parent_chunks, child_chunks)
            parent_chunks, child_chunks = self._chunker.chunk_markdown(
                md_text,  # ← MARKDOWN INPUT: Raw text passed to chunker
                source_path=str(file_path),
                pdf_stem=pdf_stem
            )
            # ↑ TUPLE OUTPUT: (parent_chunks, child_chunks) created here!
            
            # ========================================
            # STEP 3: RESULT PACKAGING
            # ========================================
            # Create chunked document object containing the results
            chunked_doc = ChunkedDocument(
                source_path=str(file_path),
                pdf_stem=pdf_stem,
                parent_chunks=parent_chunks,  # ← PARENT CHUNKS from tuple
                child_chunks=child_chunks,    # ← CHILD CHUNKS from tuple
                config=self.config.__dict__
            )
            
            # Save output if requested (optional file saving)
            if self.config.save_chunks_to_files:
                self._save_chunked_document(chunked_doc, output_path, output_filename)
            
            self.logger.info(
                f"Chunking completed successfully. "
                f"Created {chunked_doc.total_parents} parent chunks and "
                f"{chunked_doc.total_children} child chunks"
            )
            
            return chunked_doc
            
        except Exception as e:
            if isinstance(e, (FileError, ChunkingError)):
                raise
            else:
                raise ChunkingError(
                    f"Unexpected error during chunking: {e}",
                    document_path=str(file_path),
                    original_error=str(e)
                )
    
    def chunk_directory(
        self,
        directory_path: Union[str, Path],
        *,
        file_pattern: str = "*.md",
        output_path: Optional[Union[str, Path]] = None,
        recursive: bool = False
    ) -> List[ChunkedDocument]:
        """
        Chunk all markdown files in a directory.
        
        Args:
            directory_path: Path to the directory
            file_pattern: File pattern to match
            output_path: Custom output directory
            recursive: Whether to process subdirectories recursively
            
        Returns:
            List of ChunkedDocument objects
            
        Raises:
            FileError: If directory operations fail
        """
        try:
            directory_path = Path(directory_path)
            if not directory_path.exists() or not directory_path.is_dir():
                raise FileError(
                    f"Directory not found: {directory_path}",
                    file_path=str(directory_path),
                    operation="directory_validation"
                )
            
            # Find markdown files
            if recursive:
                markdown_files = list(directory_path.rglob(file_pattern))
            else:
                markdown_files = list(directory_path.glob(file_pattern))
            
            if not markdown_files:
                self.logger.warning(f"No markdown files found in {directory_path}")
                return []
            
            self.logger.info(f"Found {len(markdown_files)} markdown files to process")
            
            # Process files
            if self.config.parallel_processing:
                return self._chunk_files_parallel(markdown_files, output_path)
            else:
                return self._chunk_files_sequential(markdown_files, output_path)
                
        except Exception as e:
            if isinstance(e, FileError):
                raise
            else:
                raise FileError(
                    f"Failed to process directory: {e}",
                    file_path=str(directory_path),
                    operation="directory_processing"
                )
    
    def _chunk_files_sequential(
        self, 
        files: List[Path], 
        output_path: Optional[Union[str, Path]]
    ) -> List[ChunkedDocument]:
        """Process files sequentially."""
        results = []
        progress_bar = self._progress_manager.create_progress_bar(
            len(files), "Processing files"
        )
        
        for file_path in files:
            try:
                result = self.chunk_file(file_path, output_path=output_path)
                results.append(result)
            except Exception as e:
                self.logger.error(f"Failed to process {file_path}: {e}")
            finally:
                progress_bar.update(1)
        
        progress_bar.close()
        return results
    
    def _chunk_files_parallel(
        self, 
        files: List[Path], 
        output_path: Optional[Union[str, Path]]
    ) -> List[ChunkedDocument]:
        """Process files in parallel."""
        results = []
        progress_bar = self._progress_manager.create_progress_bar(
            len(files), "Processing files"
        )
        
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            future_to_file = {
                executor.submit(self.chunk_file, file_path, output_path=output_path): file_path
                for file_path in files
            }
            
            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    self.logger.error(f"Failed to process {file_path}: {e}")
                finally:
                    progress_bar.update(1)
        
        progress_bar.close()
        return results
    
    def _extract_pdf_stem(self, file_path: Union[str, Path]) -> Optional[str]:
        """Extract PDF stem from file path if it exists in the path."""
        # Convert to Path if it's a string
        if isinstance(file_path, str):
            file_path = Path(file_path)
        
        # Look for PDF stem in the path (e.g., from 'out/Headache/output.md' extract 'Headache')
        path_parts = file_path.parts
        
        # Check if we're in an 'out' directory structure
        if 'out' in path_parts:
            out_index = path_parts.index('out')
            if out_index + 1 < len(path_parts):
                potential_stem = path_parts[out_index + 1]
                # Verify it's not a file extension
                if '.' not in potential_stem:
                    return potential_stem
        
        # Also check for test_out or similar directory structures
        for part in path_parts:
            if part.endswith('_out') or part == 'out':
                # Find the next directory after this one
                try:
                    part_index = path_parts.index(part)
                    if part_index + 1 < len(path_parts):
                        potential_stem = path_parts[part_index + 1]
                        if '.' not in potential_stem:  # Not a file
                            return potential_stem
                except ValueError:
                    continue
        
        return None
    
    def _save_chunked_document(
        self,
        chunked_doc: ChunkedDocument,
        output_path: Optional[Union[str, Path]],
        output_filename: Optional[str]
    ) -> None:
        """Save chunked document to separate parent and child chunk files."""
        try:
            # Determine output directory
            if output_path:
                output_dir = Path(output_path)
            else:
                output_dir = Path(self.config.output_directory)
            
            # Ensure output directory exists
            ensure_directory(output_dir)
            
            # Extract PDF stem from source path for subdirectory creation
            source_path = Path(chunked_doc.source_path)
            pdf_stem = chunked_doc.pdf_stem or source_path.stem
            
            # Create PDF stem subdirectory if we have a PDF stem
            if pdf_stem and pdf_stem != source_path.stem:
                pdf_output_dir = output_dir / pdf_stem
                ensure_directory(pdf_output_dir)
            else:
                pdf_output_dir = output_dir
            
            # Save parent chunks
            parent_chunks_file = pdf_output_dir / "parent_chunks.json"
            parent_data = {
                "source_path": chunked_doc.source_path,
                "pdf_stem": chunked_doc.pdf_stem,
                "total_parents": chunked_doc.total_parents,
                "chunking_strategy": chunked_doc.chunking_strategy,
                "config": chunked_doc.config,
                "parent_chunks": [chunk.to_dict() for chunk in chunked_doc.parent_chunks]
            }
            
            with open(parent_chunks_file, "w", encoding="utf-8") as f:
                json.dump(parent_data, f, indent=2, ensure_ascii=False)
            
            # Save child chunks
            child_chunks_file = pdf_output_dir / "child_chunks.json"
            child_data = {
                "source_path": chunked_doc.source_path,
                "pdf_stem": chunked_doc.pdf_stem,
                "total_children": chunked_doc.total_children,
                "chunking_strategy": chunked_doc.chunking_strategy,
                "config": chunked_doc.config,
                "child_chunks": [chunk.to_dict() for chunk in chunked_doc.child_chunks]
            }
            
            with open(child_chunks_file, "w", encoding="utf-8") as f:
                json.dump(child_data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"Saved parent chunks to: {parent_chunks_file}")
            self.logger.info(f"Saved child chunks to: {child_chunks_file}")
            
        except Exception as e:
            self.logger.warning(f"Failed to save chunked document: {e}")
    
    def get_chunking_summary(self, chunked_docs: List[ChunkedDocument]) -> Dict[str, Any]:
        """Generate a summary of chunking results."""
        total_files = len(chunked_docs)
        total_parents = sum(doc.total_parents for doc in chunked_docs)
        total_children = sum(doc.total_children for doc in chunked_docs)
        
        # Calculate average chunks per document
        avg_parents = total_parents / total_files if total_files > 0 else 0
        avg_children = total_children / total_files if total_files > 0 else 0
        
        # Get unique PDF stems
        pdf_stems = list(set(doc.pdf_stem for doc in chunked_docs if doc.pdf_stem))
        
        return {
            "total_files_processed": total_files,
            "total_parent_chunks": total_parents,
            "total_child_chunks": total_children,
            "average_parents_per_file": round(avg_parents, 2),
            "average_children_per_file": round(avg_children, 2),
            "unique_pdf_stems": pdf_stems,
            "chunking_config": self.config.__dict__
        }

    def chunk_text(
        self, 
        markdown_text: str,
        *,
        source_path: Optional[str] = None,
        pdf_stem: Optional[str] = None
    ) -> ChunkedDocument:
        """
        Chunk markdown text directly.
        
        Args:
            markdown_text: Markdown text to chunk
            source_path: Optional source path for reference
            pdf_stem: Optional PDF filename stem for identification
            
        Returns:
            ChunkedDocument containing all chunk information
            
        Raises:
            ChunkingError: If chunking fails
        """
        try:
            self.logger.info(f"Chunking markdown text (length: {len(markdown_text)} chars)")
            
            # ========================================
            # STEP 1: MARKDOWN TEXT INPUT PROCESSING
            # ========================================
            # Extract PDF stem from path if available (for organization)
            if not pdf_stem and source_path:
                pdf_stem = self._extract_pdf_stem(source_path)
            
            # ========================================
            # STEP 2: CORE CHUNKING LOGIC
            # ========================================
            # This is where the magic happens - the _chunker processes the markdown text
            # and returns the tuple (parent_chunks, child_chunks)
            parent_chunks, child_chunks = self._chunker.chunk_markdown(
                markdown_text,  # ← MARKDOWN INPUT: Raw text passed directly to chunker
                source_path=source_path,
                pdf_stem=pdf_stem
            )
            # ↑ TUPLE OUTPUT: (parent_chunks, child_chunks) created here!
            
            # ========================================
            # STEP 3: RESULT PACKAGING
            # ========================================
            # Create chunked document object containing the results
            chunked_doc = ChunkedDocument(
                source_path=source_path or "text_input",
                pdf_stem=pdf_stem,
                parent_chunks=parent_chunks,  # ← PARENT CHUNKS from tuple
                child_chunks=child_chunks,    # ← CHILD CHUNKS from tuple
                config=self.config.__dict__
            )
            
            self.logger.info(
                f"Chunking completed successfully. "
                f"Created {chunked_doc.total_parents} parent chunks and "
                f"{chunked_doc.total_children} child chunks"
            )
            
            return chunked_doc
            
        except Exception as e:
            if isinstance(e, ChunkingError):
                raise
            else:
                raise ChunkingError(
                    f"Unexpected error during text chunking: {e}",
                    document_path=source_path,
                    original_error=str(e)
                )
