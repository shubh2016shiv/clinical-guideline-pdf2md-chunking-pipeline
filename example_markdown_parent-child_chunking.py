#!/usr/bin/env python3
"""
Parent-Child Document Chunker Usage Example
===================================================

Demonstrates how to use the parent-child document chunker module to process
markdown documents into hierarchical chunks. This example shows the complete
workflow from document processing to JSON export for vector databases.

Key Features:
    - Document processing with configurable chunking parameters
    - Transformation of raw chunks into structured formats
    - Export to JSON files for vector database ingestion
    - Visualization of parent-child relationships

This example demonstrates:
    - How to initialize and configure the chunker
    - How to process a single document
    - How to transform and export the results as parent and child chunks to JSON files
    - How to visualize the chunking structure
"""

import sys
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

from parent_child_document_chunker import DocumentChunker, ChunkingConfig

# ============================================================================
# Configuration Constants
# ============================================================================

# Chunking parameters optimized for typical embedding models (e.g., OpenAI, Cohere)
DEFAULT_CHILD_TOKEN_LIMIT = 300  # Fits within most embedding model limits
DEFAULT_OVERLAP_TOKENS = 50  # Preserves context across chunk boundaries
MIN_CHUNK_SIZE = 50  # Prevents fragmented chunks

# Example document path - adjust to your actual file location
DEMO_DOCUMENT = "demonstration/chunking_demo/clinical_guidelines_markdown_examples/2025 AHA-ACC Hypertension Guideline.md"

# Output configuration
EXPORT_DIR = Path("vector_db_exports")
PARENT_CHUNKS_FILE = "parent_chunks.json"
CHILD_CHUNKS_FILE = "child_chunks.json"
METADATA_FILE = "document_metadata.json"


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class ChunkingResult:
    """Encapsulates the complete result of document chunking operation."""
    document_name: str
    source_path: str
    parent_count: int
    child_count: int
    avg_children_per_parent: float
    parent_chunks: List[Dict]
    child_chunks: List[Dict]

    def summary(self) -> str:
        """Generate a human-readable summary of chunking results."""
        return (
            f"Document: {self.document_name}\n"
            f"  Parents: {self.parent_count}\n"
            f"  Children: {self.child_count}\n"
            f"  Avg Children/Parent: {self.avg_children_per_parent:.1f}"
        )


# ============================================================================
# Core Chunking Logic
# ============================================================================

def chunk_document(file_path: str, config: Optional[ChunkingConfig] = None) -> Optional[ChunkingResult]:
    """
    Process a single document into parent-child chunks.

    Args:
        file_path: Path to the markdown document
        config: Optional custom chunking configuration

    Returns:
        ChunkingResult object containing all chunks and metadata, or None on failure

    Process Flow:
        1. Validate input file
        2. Initialize chunker with configuration
        3. Process document into hierarchical chunks
        4. Transform into export-ready format
    """
    source_path = Path(file_path)

    # Validate input
    if not source_path.exists():
        print(f"Error: Document not found at {file_path}")
        return None

    # Use default config if none provided
    if config is None:
        config = ChunkingConfig(
            child_token_limit=DEFAULT_CHILD_TOKEN_LIMIT,
            child_overlap_tokens=DEFAULT_OVERLAP_TOKENS,
            min_chunk_tokens=MIN_CHUNK_SIZE,
            enable_progress=False,  # Suppress verbose progress for clean output
            save_chunks_to_files=False  # We'll handle exports ourselves
        )

    try:
        # Initialize and execute chunking
        chunker = DocumentChunker(config)
        raw_result = chunker.chunk_file(str(source_path))

        # Transform raw chunks into structured export format
        parent_chunks = _transform_parent_chunks(raw_result)
        child_chunks = _transform_child_chunks(raw_result)

        # Calculate metrics
        avg_children = (
            len(child_chunks) / len(parent_chunks)
            if parent_chunks else 0
        )

        return ChunkingResult(
            document_name=raw_result.pdf_stem or source_path.stem,
            source_path=str(source_path),
            parent_count=len(parent_chunks),
            child_count=len(child_chunks),
            avg_children_per_parent=avg_children,
            parent_chunks=parent_chunks,
            child_chunks=child_chunks
        )

    except Exception as e:
        print(f"Error during chunking: {e}")
        return None


def _transform_parent_chunks(raw_result) -> List[Dict]:
    """
    Transform raw parent chunks into vector database format.

    Parent chunks serve as context containers and should include:
        - Full section content
        - Hierarchical metadata (header level, section path)
        - List of associated child chunk IDs
    """
    parent_chunks = []

    for parent in raw_result.parent_chunks:
        # Find all children belonging to this parent
        child_ids = [
            child.metadata["chunk_id"]
            for child in raw_result.child_chunks
            if child.metadata.get("parent_chunk_id") == parent.metadata["chunk_id"]
        ]

        parent_chunks.append({
            "chunk_id": parent.metadata["chunk_id"],
            "content": parent.page_content,
            "metadata": {
                "document_id": parent.metadata["parent_doc_id"],
                "header": parent.metadata["header"],
                "header_level": parent.metadata["header_level"],
                "section_path": parent.metadata["section_path"],
                "token_count": parent.metadata["token_count"],
                "line_start": parent.metadata["start_line"],
                "line_end": parent.metadata["end_line"],
                "child_chunk_ids": child_ids,  # Links to children
                "child_count": len(child_ids)
            }
        })

    return parent_chunks


def _transform_child_chunks(raw_result) -> List[Dict]:
    """
    Transform raw child chunks into vector database format.

    Child chunks are optimized for embedding and search:
        - Content within embedding model token limits
        - Reference to parent for context expansion
        - Metadata for filtering and ranking
    """
    child_chunks = []

    for child in raw_result.child_chunks:
        child_chunks.append({
            "chunk_id": child.metadata["chunk_id"],
            "content": child.page_content,
            "metadata": {
                "document_id": child.metadata["parent_doc_id"],
                "parent_chunk_id": child.metadata.get("parent_chunk_id"),  # Link to parent
                "header": child.metadata["header"],
                "section_path": child.metadata["section_path"],
                "token_count": child.metadata.get("token_count"),
                "chunk_index": child.metadata.get("chunk_index"),
                "block_types": child.metadata.get("block_types", []),
                "line_start": child.metadata["start_line"],
                "line_end": child.metadata["end_line"]
            }
        })

    return child_chunks


# ============================================================================
# Export Functions
# ============================================================================

def export_chunks(result: ChunkingResult, output_dir: Path = EXPORT_DIR) -> Tuple[Path, Path, Path]:
    """
    Export chunks to separate JSON files following best practices.

    Rationale for separate files:
        - Parent and child chunks serve different purposes in RAG systems
        - Separate storage allows for independent querying and caching
        - Reduces redundancy when only one type is needed
        - Facilitates different embedding strategies per chunk type

    Args:
        result: ChunkingResult containing all chunks
        output_dir: Directory for export files

    Returns:
        Tuple of (parent_file_path, child_file_path, metadata_file_path)

    File Structure:
        - parent_chunks.json: Array of parent chunk objects
        - child_chunks.json: Array of child chunk objects
        - document_metadata.json: Document-level metadata and statistics
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Export parent chunks
    parent_file = output_dir / PARENT_CHUNKS_FILE
    with open(parent_file, 'w', encoding='utf-8') as f:
        json.dump(result.parent_chunks, f, indent=2, ensure_ascii=False)

    # Export child chunks
    child_file = output_dir / CHILD_CHUNKS_FILE
    with open(child_file, 'w', encoding='utf-8') as f:
        json.dump(result.child_chunks, f, indent=2, ensure_ascii=False)

    # Export document metadata
    metadata = {
        "document_name": result.document_name,
        "source_path": result.source_path,
        "statistics": {
            "total_parent_chunks": result.parent_count,
            "total_child_chunks": result.child_count,
            "avg_children_per_parent": round(result.avg_children_per_parent, 2)
        },
        "files": {
            "parent_chunks": PARENT_CHUNKS_FILE,
            "child_chunks": CHILD_CHUNKS_FILE
        }
    }

    metadata_file = output_dir / METADATA_FILE
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    return parent_file, child_file, metadata_file


# ============================================================================
# Visualization and Reporting
# ============================================================================

def print_sample_chunks(result: ChunkingResult, num_samples: int = 3):
    """
    Display sample chunks to visualize the chunking structure.

    Args:
        result: ChunkingResult to sample from
        num_samples: Number of parent-child groups to display
    """
    print("\n" + "=" * 80)
    print("SAMPLE CHUNK STRUCTURE")
    print("=" * 80)

    for i, parent in enumerate(result.parent_chunks[:num_samples], 1):
        parent_id = parent["chunk_id"]

        # Display parent chunk info
        print(f"\n[Parent {i}] {parent['metadata']['header']}")
        print(f"  ID: {parent_id}")
        print(f"  Section: {parent['metadata']['section_path']}")
        print(f"  Tokens: {parent['metadata']['token_count']}")
        print(f"  Content Preview: {parent['content'][:100]}...")

        # Display associated child chunks
        child_ids = parent['metadata']['child_chunk_ids']
        children = [c for c in result.child_chunks if c['chunk_id'] in child_ids]

        print(f"\n  Children ({len(children)}):")
        for j, child in enumerate(children, 1):
            print(f"    [{j}] ID: {child['chunk_id']}")
            print(f"        Tokens: {child['metadata']['token_count']}")
            print(f"        Preview: {child['content'][:80]}...")


# ============================================================================
# Main Execution
# ============================================================================

def main():
    """
    Main execution function demonstrating the complete workflow.

    Workflow:
        1. Chunk document into parent-child structure
        2. Export to separate JSON files
        3. Display sample results
        4. Provide integration guidance
    """
    print("=" * 80)
    print("PARENT-CHILD DOCUMENT CHUNKING DEMONSTRATION")
    print("=" * 80)
    print(f"\nProcessing: {DEMO_DOCUMENT}")

    # Step 1: Chunk the document
    result = chunk_document(DEMO_DOCUMENT)

    if result is None:
        print("\nChunking failed. Please check the document path and try again.")
        return 1

    # Step 2: Display results summary
    print("\n" + "-" * 80)
    print("CHUNKING RESULTS")
    print("-" * 80)
    print(result.summary())

    # Step 3: Export to JSON files
    print("\n" + "-" * 80)
    print("EXPORTING CHUNKS")
    print("-" * 80)
    parent_file, child_file, metadata_file = export_chunks(result)
    print(f"# Parent chunks: {parent_file} ({result.parent_count} chunks)")
    print(f"* Child chunks:  {child_file} ({result.child_count} chunks)")
    print(f"- Metadata:      {metadata_file}")

    # Step 4: Visualize sample chunks
    print_sample_chunks(result, num_samples=5)

    print("\n" + "=" * 80)
    print("✓ Demonstration complete!")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())