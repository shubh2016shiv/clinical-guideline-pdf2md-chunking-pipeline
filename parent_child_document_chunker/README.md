# Document Chunker Module

A professional, enterprise-grade module for structure-aware parent/child chunking of markdown documents. This module provides intelligent chunking that preserves document hierarchy while creating searchable, manageable content chunks.

## 🚀 Features

- **Structure-Aware Chunking**: Based on markdown headers and document structure
- **Parent/Child Relationships**: Maintains hierarchical relationships between chunks
- **Configurable Token Limits**: Adjustable chunk sizes and overlap for different use cases
- **Parallel Processing**: Support for concurrent processing of multiple files
- **Comprehensive Metadata**: Rich metadata tracking for each chunk
- **Progress Monitoring**: Visual progress bars with fallback support
- **Multiple Output Formats**: JSON, markdown, and CSV output options
- **CLI Interface**: Easy-to-use command-line tools
- **Enterprise Standards**: Type hints, comprehensive error handling, and logging

## 📁 Module Structure

```
document_chunker/
├── __init__.py              # Main package exports
├── cli.py                   # Command-line interface
├── example_usage.py         # Usage examples
├── test_chunker.py          # Module tests
├── core/                    # Core chunking logic
│   ├── __init__.py
│   ├── chunker.py          # StructureAwareChunker
│   └── processor.py        # DocumentChunker
├── models/                  # Data models
│   ├── __init__.py
│   ├── config.py           # ChunkingConfig
│   └── chunks.py           # ChunkedDocument, ChunkMetadata
├── utils/                   # Utility functions
│   ├── __init__.py
│   ├── file_utils.py       # File operations
│   └── progress.py         # Progress management
└── exceptions/              # Exception hierarchy
    ├── __init__.py
    ├── base.py             # Base exceptions
    └── processing.py       # Processing-specific exceptions
```

## 🔧 Installation

The module is ready to use. Ensure you have the required dependencies:

```bash
pip install tiktoken tqdm
```

## 📖 Quick Start

### Basic Usage

```python
from parent_child_document_chunker import DocumentChunker, ChunkingConfig

# Create configuration
config = ChunkingConfig(
    child_token_limit=450,
    child_overlap_tokens=40,
    parallel_processing=True
)

# Initialize chunker
chunker = DocumentChunker(config)

# Chunk a single file
result = chunker.chunk_file("document.md")

# Chunk a directory
results = chunker.chunk_directory("out/", recursive=True)
```

### Command Line Interface

```bash
# Chunk a single file
python -m parent_child_document_chunker.cli chunk-file document.md

# Chunk all markdown files in a directory
python -m parent_child_document_chunker.cli chunk-dir out/

# Custom configuration
python -m parent_child_document_chunker.cli chunk-dir out/ --token-limit 300 --overlap 50 --parallel

# Save results to files
python -m parent_child_document_chunker.cli chunk-dir out/ --save-files --output-dir chunks/
```

## 🎯 How It Works

### Parent/Child Chunking Strategy

1. **Document Parsing**: Analyzes markdown structure and identifies headers
2. **Section Extraction**: Creates parent chunks for each header section
3. **Atomic Block Identification**: Identifies atomic blocks (tables, code, blockquotes, lists, paragraphs)
4. **Smart Chunking**: Combines atomic blocks into child chunks based on token budget
5. **Relationship Preservation**: Maintains parent-child links for context

### Chunk Types

- **Parent Chunks**: Full sections with headers (provides context and structure)
- **Child Chunks**: Smaller, focused chunks optimized for retrieval and processing

### Atomic Blocks

- **Tables**: Complete table structures (header + separator + data)
- **Code Fences**: Complete code blocks
- **Blockquotes**: Contiguous quoted content (preserves figure bundles)
- **Lists**: Contiguous list items
- **Paragraphs**: Text content between structural elements

## ⚙️ Configuration Options

### Chunking Parameters

- `child_token_limit`: Maximum tokens per child chunk (default: 450)
- `child_overlap_tokens`: Token overlap between consecutive chunks (default: 40)
- `min_chunk_tokens`: Minimum tokens required for a chunk (default: 60)

### Processing Options

- `parallel_processing`: Enable concurrent processing (default: False)
- `max_workers`: Number of parallel workers (default: 4)
- `enable_progress`: Show progress bars (default: True)

### Output Options

- `save_chunks_to_files`: Save results to JSON files (default: False)
- `output_directory`: Directory for saved files (default: "chunked_documents")
- `include_metadata`: Include comprehensive metadata (default: True)

## 📊 Output Format

### ChunkedDocument Structure

```python
{
    "source_path": "path/to/document.md",
    "pdf_stem": "document_name",
    "total_parents": 5,
    "total_children": 12,
    "chunking_strategy": "structure_aware_md_v1",
    "parent_chunks": [...],
    "child_chunks": [...],
    "config": {...}
}
```

### ChunkMetadata Fields

- `chunk_id`: Unique identifier for the chunk
- `parent_doc_id`: Link to parent chunk
- `doc_level`: "parent" or "child"
- `header`: Section header text
- `header_level`: Header hierarchy level
- `section_path`: Breadcrumb path (e.g., "Introduction > Section 1 > Subsection")
- `block_types`: Types of content blocks in the chunk
- `start_line`/`end_line`: Line numbers in source file
- `token_count`: Estimated token count
- `source_path`: Path to source file
- `pdf_stem`: PDF filename stem

## 🔍 Use Cases

### Information Retrieval
- Create searchable chunks while maintaining context
- Enable semantic search across document sections
- Support for RAG (Retrieval-Augmented Generation) systems

### Document Analysis
- Analyze document structure and content distribution
- Extract key sections and subsections
- Process large documents in manageable pieces

### Content Processing
- Feed chunks to LLMs for analysis
- Extract specific information from sections
- Maintain document hierarchy in processing pipelines

## 🧪 Testing

Run the test suite to verify the module works correctly:

```bash
python parent_child_document_chunker/test_suite.py
```

## 📝 Examples

See `example_usage.py` for comprehensive usage examples:

```bash
python parent_child_document_chunker/usage_examples.py
```

## 🚀 Next Steps

1. **Process Your Documents**: Use the CLI to chunk your markdown files from the `out` directory
2. **Customize Configuration**: Adjust token limits and overlap for your specific needs
3. **Integrate with Your Pipeline**: Use the Python API in your applications
4. **Extend Functionality**: Add custom chunking strategies or output formats

## 🤝 Contributing

The module follows enterprise coding standards:
- Comprehensive type hints
- Extensive error handling
- Professional logging
- Modular architecture
- Comprehensive testing

## 📄 License

This module is part of the document processing pipeline and follows the same licensing terms.
