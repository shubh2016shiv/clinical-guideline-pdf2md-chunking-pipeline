# Async API Integration Guide for Document Processing

A comprehensive guide to integrating the asynchronous document processing API with modern web frameworks and applications.

## Table of Contents

- [Chapter 1: Introduction](#chapter-1-introduction)
  - [What is the Async API?](#what-is-the-async-api)
  - [When to Use Async vs Sync](#when-to-use-async-vs-sync)
  - [Key Benefits](#key-benefits)
- [Chapter 2: Core Concepts](#chapter-2-core-concepts)
  - [Understanding Async/Await](#understanding-asyncawait)
  - [Non-blocking I/O](#non-blocking-io)
  - [Concurrency and Parallelism](#concurrency-and-parallelism)
  - [Result Structure](#result-structure)
- [Chapter 3: Configuration Deep Dive](#chapter-3-configuration-deep-dive)
  - [BatchConfiguration Parameters](#batchconfiguration-parameters)
  - [DocumentProcessingConfig Parameters](#documentprocessingconfig-parameters)
  - [Environment Variables](#environment-variables)
  - [Configuration Best Practices](#configuration-best-practices)
- [Chapter 4: Complete API Reference](#chapter-4-complete-api-reference)
  - [convert_pdf_batch_to_markdown_async](#convert_pdf_batch_to_markdown_async)
  - [convert_single_pdf_to_markdown_async](#convert_single_pdf_to_markdown_async)
  - [convert_directory_pdfs_to_markdown_async](#convert_directory_pdfs_to_markdown_async)
  - [convert_concurrent_batches_async](#convert_concurrent_batches_async)
  - [get_default_conversion_settings_async](#get_default_conversion_settings_async)
- [Chapter 5: FastAPI Integration Tutorial](#chapter-5-fastapi-integration-tutorial)
  - [Project Setup](#project-setup)
  - [Building a Complete API Service](#building-a-complete-api-service)
  - [Advanced Features](#advanced-features)
  - [Production Deployment](#production-deployment)
- [Chapter 6: Practical Examples](#chapter-6-practical-examples)
  - [Basic Document Processing](#basic-document-processing)
  - [Batch Processing with Progress](#batch-processing-with-progress)
  - [Error Handling and Retries](#error-handling-and-retries)
  - [Custom Output Management](#custom-output-management)
- [Chapter 7: Performance Optimization](#chapter-7-performance-optimization)
  - [Concurrency Tuning](#concurrency-tuning)
  - [Resource Management](#resource-management)
  - [Memory Optimization](#memory-optimization)
- [Chapter 8: Troubleshooting](#chapter-8-troubleshooting)
  - [Common Issues](#common-issues)
  - [Debugging Tips](#debugging-tips)
  - [Performance Issues](#performance-issues)
- [Chapter 9: Migration Guide](#chapter-9-migration-guide)
  - [From Sync to Async](#from-sync-to-async)
  - [Upgrading Existing Code](#upgrading-existing-code)

## Chapter 1: Introduction

### What is the Async API?

The document processing pipeline provides two distinct APIs for converting PDF documents to Markdown:

- **Synchronous API**: Simple, blocking calls that work in any Python context
- **Asynchronous API**: Non-blocking, concurrent processing using Python's `async/await` syntax

The async API is built on top of the same core processing engine but provides:
- **Non-blocking execution**: Your application can handle other tasks while documents are being processed
- **Concurrent processing**: Multiple documents can be processed simultaneously
- **Web framework integration**: Perfect for FastAPI, aiohttp, and other async frameworks
- **Resource efficiency**: Better utilization of system resources through concurrency

### When to Use Async vs Sync

**Use the Synchronous API when:**
- Writing simple scripts or command-line tools
- Working in Jupyter notebooks
- Building desktop applications
- You don't need concurrent processing
- You want the simplest possible integration

**Use the Asynchronous API when:**
- Building web APIs (FastAPI, aiohttp, etc.)
- Processing multiple documents concurrently
- Building microservices
- Need non-blocking I/O for better performance
- Integrating with existing async applications

### Key Benefits

1. **Performance**: Process multiple documents simultaneously without blocking
2. **Scalability**: Handle more requests with the same resources
3. **Integration**: Seamlessly works with modern async web frameworks
4. **Resource Efficiency**: Better CPU and memory utilization
5. **User Experience**: Non-blocking operations keep applications responsive

## Chapter 2: Core Concepts

### Understanding Async/Await

The async API uses Python's `async/await` syntax for asynchronous programming:

```python
import asyncio
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown_async

# Define an async function
async def process_documents():
    # Use 'await' to call async functions
    results = await convert_pdf_batch_to_markdown_async(
        pdf_paths=["doc1.pdf", "doc2.pdf"],
        enable_gemini=True,
        max_concurrent=5
    )
    return results

# Run the async function using asyncio.run()
results = asyncio.run(process_documents())
```

**Key Points:**
- `async def` declares an asynchronous function
- `await` pauses execution until the async operation completes
- `asyncio.run()` starts the event loop and runs the async function
- Async functions can only be called from other async functions or with `asyncio.run()`

### Non-blocking I/O

The async API performs non-blocking I/O operations:

```python
# This doesn't block - other code can run while processing
async def process_large_batch():
    results = await convert_pdf_batch_to_markdown_async(
        pdf_paths=large_list_of_pdfs,  # 100+ documents
        max_concurrent=10
    )
    # While processing, your application can handle other requests
    return results
```

**Benefits:**
- Your application remains responsive during processing
- Multiple requests can be handled simultaneously
- Better resource utilization

### Concurrency and Parallelism

The async API processes multiple documents concurrently:

```python
async def concurrent_processing():
    # Process 5 documents simultaneously
    results = await convert_pdf_batch_to_markdown_async(
        pdf_paths=["doc1.pdf", "doc2.pdf", "doc3.pdf", "doc4.pdf", "doc5.pdf"],
        max_concurrent=5  # Process all 5 at the same time
    )
    return results
```

**Concurrency Control:**
- `max_concurrent` parameter controls how many documents process simultaneously
- Higher values = more parallelism but more resource usage
- Lower values = less parallelism but more stable resource usage

### Result Structure

All async functions return structured results:

```python
# Example result structure
{
    'pdf_path': 'document.pdf',           # Original file path
    'success': True,                      # Whether processing succeeded
    'result': DocumentResult(...),        # Processing results (if successful)
    'error': None,                        # Error message (if failed)
    'attempts': 1,                        # Number of processing attempts
    'duration': 45.3                      # Processing time in seconds
}
```

**DocumentResult contains:**
- `markdown_path`: Path to generated Markdown file
- `figures`: List of extracted figures
- `tables`: List of extracted tables
- `metadata`: Document processing metadata

## Chapter 3: Configuration Deep Dive

Understanding configuration is crucial for optimal performance and functionality. The async API uses two main configuration classes.

### BatchConfiguration Parameters

Controls how multiple documents are processed concurrently:

```python
from doc2md_conversion_engine.orchestration.configuration.batch_configuration import BatchConfiguration

# Create a custom batch configuration
batch_config = BatchConfiguration(
    # Concurrency Settings
    max_concurrent_tasks=10,           # Process up to 10 documents simultaneously
    max_concurrent_processors=5,       # Use up to 5 processor instances
    
    # Retry Configuration
    enable_retries=True,               # Enable automatic retries
    max_retries_per_task=3,            # Retry failed tasks up to 3 times
    retry_delay_seconds=2.0,           # Wait 2 seconds between retries
    exponential_backoff=True,          # Double delay after each retry
    
    # Performance Optimization
    enable_processor_pooling=True,     # Reuse processor instances (recommended)
    processor_pool_size=5,             # Keep 5 processors in the pool
    task_timeout_seconds=300,          # 5-minute timeout per task
    
    # Fault Tolerance
    continue_on_error=True,            # Continue batch if individual tasks fail
    circuit_breaker_threshold=5,       # Open circuit after 5 consecutive failures
    circuit_breaker_timeout=60,        # Reset circuit breaker after 60 seconds
    
    # Progress and Logging
    enable_progress_reporting=True,    # Show progress bars
    log_level="INFO"                   # Logging verbosity
)
```

**Key Parameters Explained:**

| Parameter | Default | Description | When to Change |
|-----------|---------|-------------|----------------|
| `max_concurrent_tasks` | 5 | Documents processed simultaneously | Increase for more parallelism |
| `max_concurrent_processors` | 3 | Processor instances running | Should be ≤ max_concurrent_tasks |
| `enable_processor_pooling` | True | Reuse processors (faster) | Keep True for batch processing |
| `processor_pool_size` | 3 | Processors kept in pool | Increase for high concurrency |
| `max_retries_per_task` | 3 | Retry attempts per document | Increase for unreliable networks |
| `task_timeout_seconds` | None | Timeout per document | Set for very large documents |

### DocumentProcessingConfig Parameters

Controls how individual documents are processed:

```python
from doc2md_conversion_engine.models.config import DocumentProcessingConfig

# Create a custom document processing configuration
doc_config = DocumentProcessingConfig(
    # Output Settings
    output_dir="/path/to/output",      # Base output directory
    enable_datetime_subdir=True,       # Create timestamped subdirectories
    sanitize_filenames=True,           # Clean invalid filename characters
    
    # Processing Options
    extract_tables=True,               # Extract tables from documents
    write_table_csv=True,              # Save tables as CSV files
    save_figures=True,                 # Extract and save figures
    figure_format="png",               # Figure format (png, jpg, etc.)
    
    # AI Features
    enable_gemini=True,                # Enable Gemini AI for figure analysis
    gemini_api_key="your-api-key",     # Gemini API key (or use env var)
    
    # Hardware Acceleration
    enable_gpu_acceleration=True,      # Use GPU if available
    preferred_device="auto",           # Device preference (auto, cuda, mps, cpu)
    force_cpu=False,                   # Force CPU-only processing
    
    # Docling Settings
    docling_images_scale=1.0,          # Image scaling factor
    docling_generate_pictures=True,    # Generate picture images
)
```

**Key Parameters Explained:**

| Parameter | Default | Description | When to Change |
|-----------|---------|-------------|----------------|
| `enable_gemini` | False | AI-powered figure analysis | Set True for enhanced figure processing |
| `extract_tables` | True | Extract tables from PDFs | Set False if tables not needed |
| `save_figures` | True | Extract and save figures | Set False to skip figure extraction |
| `enable_gpu_acceleration` | True | Use GPU for processing | Set False for CPU-only environments |
| `preferred_device` | "auto" | Hardware device preference | Set specific device if needed |

### Environment Variables

You can configure the API using environment variables:

```bash
# Gemini API Configuration
export GEMINI_API_KEY="your-gemini-api-key-here"

# Hardware Acceleration
export FORCE_CPU="false"                    # Force CPU-only processing
export PREFERRED_DEVICE="cuda"              # Preferred device (cuda, mps, cpu)
export CUDA_DEVICE_ID="0"                   # Specific CUDA device ID

# Logging
export LOG_LEVEL="INFO"                     # Logging level (DEBUG, INFO, WARNING, ERROR)
```

**Environment Variable Priority:**
1. Function parameters (highest priority)
2. Environment variables
3. Configuration defaults (lowest priority)

### Configuration Best Practices

**For Development:**
```python
# Development configuration - verbose logging, lower concurrency
dev_config = BatchConfiguration(
    max_concurrent_tasks=2,
    enable_progress_reporting=True,
    log_level="DEBUG"
)
```

**For Production:**
```python
# Production configuration - optimized for performance
prod_config = BatchConfiguration(
    max_concurrent_tasks=10,
    enable_processor_pooling=True,
    processor_pool_size=5,
    log_level="INFO"
)
```

**For High-Volume Processing:**
```python
# High-volume configuration - maximum throughput
high_volume_config = BatchConfiguration(
    max_concurrent_tasks=20,
    max_concurrent_processors=10,
    processor_pool_size=10,
    enable_processor_pooling=True
)
```

## Chapter 4: Complete API Reference

This chapter provides detailed documentation for all async API functions with complete examples and parameter explanations.

### convert_pdf_batch_to_markdown_async

Process multiple PDF documents asynchronously with full concurrency control.

**Function Signature:**
```python
async def convert_pdf_batch_to_markdown_async(
    pdf_paths: List[str],
    output_path: Optional[str] = None,
    max_concurrent: int = 5,
    max_retries: int = 3,
    show_progress: bool = False,
    gemini_api_key: Optional[str] = None,
    enable_gemini: bool = False,
    **config_options
) -> List[Dict[str, Any]]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pdf_paths` | `List[str]` | Required | List of PDF file paths to process |
| `output_path` | `Optional[str]` | `None` | Base directory for output files |
| `max_concurrent` | `int` | `5` | Maximum documents processed simultaneously |
| `max_retries` | `int` | `3` | Retry attempts for failed documents |
| `show_progress` | `bool` | `False` | Display progress bar (not recommended for APIs) |
| `gemini_api_key` | `Optional[str]` | `None` | Gemini API key (or use GEMINI_API_KEY env var) |
| `enable_gemini` | `bool` | `False` | Enable AI-powered figure analysis |
| `**config_options` | `dict` | `{}` | Additional BatchConfiguration parameters |

**Return Value:**
```python
List[Dict[str, Any]]  # List of result dictionaries
```

**Complete Example:**
```python
import asyncio
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown_async

async def process_documents():
    """Process multiple documents with custom configuration."""
    
    # Define PDF files to process
    pdf_files = [
        "documents/report1.pdf",
        "documents/report2.pdf", 
        "documents/report3.pdf"
    ]
    
    try:
        # Process documents with custom settings
        results = await convert_pdf_batch_to_markdown_async(
            pdf_paths=pdf_files,
            output_path="/output/processed",  # Custom output directory
            max_concurrent=3,                 # Process 3 documents at once
            max_retries=2,                    # Retry failed documents twice
            enable_gemini=True,               # Enable AI figure analysis
            gemini_api_key="your-api-key",    # Explicit API key
            show_progress=True,               # Show progress (for scripts)
            # Additional configuration options
            task_timeout_seconds=300,         # 5-minute timeout per document
            enable_processor_pooling=True     # Use processor pooling
        )
        
        # Process results
        successful_count = sum(1 for r in results if r['success'])
        print(f"Successfully processed {successful_count}/{len(results)} documents")
        
        # Handle individual results
        for result in results:
            if result['success']:
                doc_result = result['result']
                print(f"✓ {result['pdf_path']}")
                print(f"  Markdown: {doc_result.markdown_path}")
                print(f"  Figures: {len(doc_result.figures)}")
                print(f"  Tables: {len(doc_result.tables)}")
                print(f"  Duration: {result['duration']:.2f}s")
            else:
                print(f"✗ {result['pdf_path']}: {result['error']}")
        
        return results
        
    except Exception as e:
        print(f"Batch processing failed: {e}")
        return []

# Run the async function
if __name__ == "__main__":
    results = asyncio.run(process_documents())
```

### convert_single_pdf_to_markdown_async

Process a single PDF document asynchronously.

**Function Signature:**
```python
async def convert_single_pdf_to_markdown_async(
    pdf_path: str,
    output_path: Optional[str] = None,
    output_filename: Optional[str] = None,
    max_retries: int = 3,
    gemini_api_key: Optional[str] = None,
    enable_gemini: bool = False,
    **config_options
) -> DocumentResult
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pdf_path` | `str` | Required | Path to PDF file to process |
| `output_path` | `Optional[str]` | `None` | Output directory (overrides config) |
| `output_filename` | `Optional[str]` | `None` | Custom filename without extension |
| `max_retries` | `int` | `3` | Retry attempts on failure |
| `gemini_api_key` | `Optional[str]` | `None` | Gemini API key |
| `enable_gemini` | `bool` | `False` | Enable AI figure analysis |
| `**config_options` | `dict` | `{}` | Additional configuration options |

**Return Value:**
```python
DocumentResult  # Direct result object (not wrapped in dict)
```

**Complete Example:**
```python
import asyncio
from doc2md_conversion_engine.orchestration import convert_single_pdf_to_markdown_async

async def process_single_document():
    """Process a single document with error handling."""
    
    pdf_file = "documents/important_report.pdf"
    
    try:
        # Process single document
        result = await convert_single_pdf_to_markdown_async(
            pdf_path=pdf_file,
            output_path="/output/single",     # Custom output directory
            output_filename="processed_report", # Custom filename
            enable_gemini=True,               # Enable AI analysis
            max_retries=5,                    # More retries for important document
            # Additional options
            extract_tables=True,              # Extract tables
            save_figures=True,                # Save figures
            figure_format="png"               # PNG format for figures
        )
        
        # Process successful result
        print(f"✓ Successfully processed: {pdf_file}")
        print(f"  Output: {result.markdown_path}")
        print(f"  Figures extracted: {len(result.figures)}")
        print(f"  Tables extracted: {len(result.tables)}")
        
        return result
        
    except Exception as e:
        print(f"✗ Failed to process {pdf_file}: {e}")
        return None

# Run the async function
if __name__ == "__main__":
    result = asyncio.run(process_single_document())
```

### convert_directory_pdfs_to_markdown_async

Process all PDF files in a directory asynchronously.

**Function Signature:**
```python
async def convert_directory_pdfs_to_markdown_async(
    directory_path: str,
    file_pattern: str = "*.pdf",
    output_path: Optional[str] = None,
    max_concurrent: int = 5,
    max_retries: int = 3,
    show_progress: bool = False,
    gemini_api_key: Optional[str] = None,
    enable_gemini: bool = False,
    **config_options
) -> Dict[str, Any]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `directory_path` | `str` | Required | Directory containing PDF files |
| `file_pattern` | `str` | `"*.pdf"` | File pattern to match (e.g., "*.pdf", "report_*.pdf") |
| `output_path` | `Optional[str]` | `None` | Base output directory |
| `max_concurrent` | `int` | `5` | Maximum concurrent processing |
| `max_retries` | `int` | `3` | Retry attempts per document |
| `show_progress` | `bool` | `False` | Show progress bar |
| `gemini_api_key` | `Optional[str]` | `None` | Gemini API key |
| `enable_gemini` | `bool` | `False` | Enable AI analysis |
| `**config_options` | `dict` | `{}` | Additional configuration |

**Return Value:**
```python
Dict[str, Any]  # Summary with results list and statistics
```

**Complete Example:**
```python
import asyncio
from pathlib import Path
from doc2md_conversion_engine.orchestration import convert_directory_pdfs_to_markdown_async

async def process_directory():
    """Process all PDFs in a directory with detailed reporting."""
    
    input_dir = "/documents/clinical_guidelines"
    output_dir = "/output/processed_guidelines"
    
    try:
        # Process all PDFs in directory
        summary = await convert_directory_pdfs_to_markdown_async(
            directory_path=input_dir,
            file_pattern="*.pdf",             # Process all PDF files
            output_path=output_dir,           # Custom output directory
            max_concurrent=8,                 # Process 8 documents concurrently
            max_retries=2,                    # Retry failed documents twice
            enable_gemini=True,               # Enable AI analysis
            show_progress=True,               # Show progress bar
            # Additional configuration
            enable_processor_pooling=True,    # Use processor pooling
            processor_pool_size=4             # Pool size for efficiency
        )
        
        # Process summary results
        print(f"Directory Processing Complete!")
        print(f"  Directory: {input_dir}")
        print(f"  Total files: {summary['total_files']}")
        print(f"  Successful: {summary['successful']}")
        print(f"  Failed: {summary['failed']}")
        print(f"  Success rate: {summary['success_rate']:.1f}%")
        print(f"  Total duration: {summary['total_duration']:.2f}s")
        
        # Show individual results
        print("\nIndividual Results:")
        for result in summary['results']:
            status = "✓" if result['success'] else "✗"
            print(f"  {status} {Path(result['pdf_path']).name}")
            if result['success']:
                doc_result = result['result']
                print(f"    Figures: {len(doc_result.figures)}, Tables: {len(doc_result.tables)}")
            else:
                print(f"    Error: {result['error']}")
        
        return summary
        
    except Exception as e:
        print(f"Directory processing failed: {e}")
        return None

# Run the async function
if __name__ == "__main__":
    summary = asyncio.run(process_directory())
```

### convert_concurrent_batches_async

Process multiple batches of documents concurrently.

**Function Signature:**
```python
async def convert_concurrent_batches_async(
    batch_paths: List[List[str]],
    output_path: Optional[str] = None,
    max_concurrent_per_batch: int = 5,
    gemini_api_key: Optional[str] = None,
    enable_gemini: bool = False,
    **config_options
) -> List[List[Dict[str, Any]]]
```

**Complete Example:**
```python
import asyncio
from doc2md_conversion_engine.orchestration import convert_concurrent_batches_async

async def process_multiple_batches():
    """Process multiple batches of documents concurrently."""
    
    # Define multiple batches
    batch1 = ["batch1/doc1.pdf", "batch1/doc2.pdf", "batch1/doc3.pdf"]
    batch2 = ["batch2/report1.pdf", "batch2/report2.pdf"]
    batch3 = ["batch3/guideline1.pdf", "batch3/guideline2.pdf", "batch3/guideline3.pdf"]
    
    all_batches = [batch1, batch2, batch3]
    
    try:
        # Process all batches concurrently
        batch_results = await convert_concurrent_batches_async(
            batch_paths=all_batches,
            output_path="/output/batches",    # Base output directory
            max_concurrent_per_batch=3,       # 3 documents per batch
            enable_gemini=True,               # Enable AI analysis
            # Additional configuration
            enable_processor_pooling=True,
            processor_pool_size=6             # Larger pool for multiple batches
        )
        
        # Process results for each batch
        for i, (batch, results) in enumerate(zip(all_batches, batch_results), 1):
            successful = sum(1 for r in results if r['success'])
            print(f"Batch {i}: {successful}/{len(results)} documents successful")
            
            for result in results:
                if result['success']:
                    print(f"  ✓ {Path(result['pdf_path']).name}")
                else:
                    print(f"  ✗ {Path(result['pdf_path']).name}: {result['error']}")
        
        return batch_results
        
    except Exception as e:
        print(f"Batch processing failed: {e}")
        return []

# Run the async function
if __name__ == "__main__":
    results = asyncio.run(process_multiple_batches())
```

### get_default_conversion_settings_async

Get default configuration parameters for async processing.

**Function Signature:**
```python
def get_default_conversion_settings_async() -> Dict[str, Any]
```

**Complete Example:**
```python
from doc2md_conversion_engine.orchestration import get_default_conversion_settings_async

# Get default settings
default_settings = get_default_conversion_settings_async()

print("Default Async Settings:")
for key, value in default_settings.items():
    print(f"  {key}: {value}")

# Customize settings
custom_settings = default_settings.copy()
custom_settings['max_concurrent'] = 10
custom_settings['enable_processor_pooling'] = True

# Use with processing function
results = await convert_pdf_batch_to_markdown_async(
    pdf_paths=pdf_files,
    **custom_settings
)
```

## Chapter 5: FastAPI Integration Tutorial

This chapter provides a complete step-by-step tutorial for building a production-ready FastAPI service using the async document processing API.

### Project Setup

**1. Create Project Structure:**
```bash
mkdir document-processing-api
cd document-processing-api

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install fastapi uvicorn python-multipart
pip install doc2md-conversion-engine  # Your package
```

**2. Project Files:**
```
document-processing-api/
├── main.py                 # FastAPI application
├── models.py               # Pydantic models
├── config.py               # Configuration settings
├── requirements.txt        # Dependencies
└── README.md              # Documentation
```

### Building a Complete API Service

**Step 1: Create Pydantic Models (`models.py`)**

```python
"""
Pydantic models for request/response validation.
"""
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
from pathlib import Path

class BatchProcessRequest(BaseModel):
    """Request model for batch document processing."""
    pdf_paths: List[str] = Field(
        ..., 
        description="List of PDF file paths to process",
        min_items=1,
        max_items=100
    )
    output_path: Optional[str] = Field(
        None, 
        description="Base directory for output files"
    )
    max_concurrent: int = Field(
        5, 
        ge=1, 
        le=20, 
        description="Maximum documents processed simultaneously"
    )
    max_retries: int = Field(
        3, 
        ge=0, 
        le=10, 
        description="Retry attempts for failed documents"
    )
    enable_gemini: bool = Field(
        False, 
        description="Enable AI-powered figure analysis"
    )
    gemini_api_key: Optional[str] = Field(
        None, 
        description="Gemini API key (or use GEMINI_API_KEY env var)"
    )
    
    @validator('pdf_paths')
    def validate_pdf_paths(cls, v):
        """Validate that all paths are PDF files."""
        for path in v:
            if not Path(path).suffix.lower() == '.pdf':
                raise ValueError(f"File must be a PDF: {path}")
            if not Path(path).exists():
                raise ValueError(f"File does not exist: {path}")
        return v

class SingleProcessRequest(BaseModel):
    """Request model for single document processing."""
    pdf_path: str = Field(..., description="Path to PDF file to process")
    output_path: Optional[str] = Field(
        None, 
        description="Output directory (overrides config)"
    )
    output_filename: Optional[str] = Field(
        None, 
        description="Custom filename without extension"
    )
    enable_gemini: bool = Field(
        False, 
        description="Enable AI-powered figure analysis"
    )
    gemini_api_key: Optional[str] = Field(
        None, 
        description="Gemini API key"
    )
    
    @validator('pdf_path')
    def validate_pdf_path(cls, v):
        """Validate PDF file path."""
        if not Path(v).suffix.lower() == '.pdf':
            raise ValueError("File must be a PDF")
        if not Path(v).exists():
            raise ValueError("File does not exist")
        return v

class ProcessingResult(BaseModel):
    """Result model for individual document processing."""
    pdf_path: str
    success: bool
    markdown_path: Optional[str] = None
    figures_count: int = 0
    tables_count: int = 0
    duration: float = 0.0
    error: Optional[str] = None
    attempts: int = 1

class BatchProcessResponse(BaseModel):
    """Response model for batch processing."""
    status: str
    total: int
    successful: int
    failed: int
    success_rate: float
    total_duration: float
    results: List[ProcessingResult]

class SingleProcessResponse(BaseModel):
    """Response model for single document processing."""
    status: str
    result: Optional[ProcessingResult] = None
    error: Optional[str] = None

class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    service: str
    version: str
    timestamp: str
```

**Step 2: Create Configuration (`config.py`)**

```python
"""
Configuration settings for the FastAPI application.
"""
import os
from typing import Optional
from pydantic import BaseSettings

class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # API Configuration
    app_name: str = "Document Processing API"
    app_version: str = "1.0.0"
    debug: bool = False
    
    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    
    # Processing Configuration
    default_max_concurrent: int = 5
    default_max_retries: int = 3
    default_timeout: int = 300  # 5 minutes
    
    # Output Configuration
    default_output_dir: str = "/tmp/processed_documents"
    
    # Gemini Configuration
    gemini_api_key: Optional[str] = None
    
    # Logging Configuration
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"
        case_sensitive = False

# Global settings instance
settings = Settings()

# Override with environment variables if present
if os.getenv("GEMINI_API_KEY"):
    settings.gemini_api_key = os.getenv("GEMINI_API_KEY")
```

**Step 3: Create Main FastAPI Application (`main.py`)**

```python
"""
FastAPI application for document processing with async support.
"""
import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

# Import async processing functions
from doc2md_conversion_engine.orchestration import (
    convert_pdf_batch_to_markdown_async,
    convert_single_pdf_to_markdown_async,
    convert_directory_pdfs_to_markdown_async
)

# Import models and config
from models import (
    BatchProcessRequest, SingleProcessRequest,
    BatchProcessResponse, SingleProcessResponse,
    ProcessingResult, HealthResponse
)
from config import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    description="Async API for PDF to Markdown conversion with AI",
    version=settings.app_version,
    debug=settings.debug
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency for getting settings
def get_settings():
    return settings

# Custom exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """Handle validation errors with detailed messages."""
    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation Error",
            "details": exc.errors(),
            "message": "Request validation failed"
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred"
        }
    )

# Health check endpoint
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint for monitoring."""
    return HealthResponse(
        status="healthy",
        service=settings.app_name,
        version=settings.app_version,
        timestamp=datetime.utcnow().isoformat()
    )

# Batch processing endpoint
@app.post("/api/v1/process/batch", response_model=BatchProcessResponse)
async def process_batch(
    request: BatchProcessRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """
    Process multiple PDF documents in batch.
    
    This endpoint processes documents concurrently and returns detailed results
    for each document. Perfect for bulk document processing scenarios.
    """
    start_time = time.time()
    logger.info(f"Starting batch processing for {len(request.pdf_paths)} documents")
    
    try:
        # Prepare processing parameters
        processing_params = {
            "pdf_paths": request.pdf_paths,
            "output_path": request.output_path or settings.default_output_dir,
            "max_concurrent": request.max_concurrent,
            "max_retries": request.max_retries,
            "show_progress": False,  # No progress bar in API
            "enable_gemini": request.enable_gemini,
            "gemini_api_key": request.gemini_api_key or settings.gemini_api_key,
            # Additional configuration
            "task_timeout_seconds": settings.default_timeout,
            "enable_processor_pooling": True
        }
        
        # Process documents asynchronously
        results = await convert_pdf_batch_to_markdown_async(**processing_params)
        
        # Convert results to response format
        processing_results = []
        successful_count = 0
        
        for result in results:
            processing_result = ProcessingResult(
                pdf_path=result['pdf_path'],
                success=result['success'],
                duration=result['duration'],
                attempts=result['attempts'],
                error=result['error'] if not result['success'] else None
            )
            
            if result['success'] and result['result']:
                doc_result = result['result']
                processing_result.markdown_path = str(doc_result.markdown_path)
                processing_result.figures_count = len(doc_result.figures)
                processing_result.tables_count = len(doc_result.tables)
                successful_count += 1
            
            processing_results.append(processing_result)
        
        total_duration = time.time() - start_time
        success_rate = (successful_count / len(results)) * 100 if results else 0
        
        logger.info(
            f"Batch processing completed: {successful_count}/{len(results)} successful "
            f"in {total_duration:.2f}s"
        )
        
        return BatchProcessResponse(
            status="completed",
            total=len(results),
            successful=successful_count,
            failed=len(results) - successful_count,
            success_rate=success_rate,
            total_duration=total_duration,
            results=processing_results
        )
        
    except Exception as e:
        logger.error(f"Batch processing failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Batch processing failed: {str(e)}"
        )

# Single document processing endpoint
@app.post("/api/v1/process/single", response_model=SingleProcessResponse)
async def process_single(
    request: SingleProcessRequest,
    settings: Settings = Depends(get_settings)
):
    """
    Process a single PDF document.
    
    This endpoint processes one document at a time. Useful for individual
    document processing or when you need precise control over each document.
    """
    logger.info(f"Processing single document: {request.pdf_path}")
    
    try:
        # Prepare processing parameters
        processing_params = {
            "pdf_path": request.pdf_path,
            "output_path": request.output_path or settings.default_output_dir,
            "output_filename": request.output_filename,
            "enable_gemini": request.enable_gemini,
            "gemini_api_key": request.gemini_api_key or settings.gemini_api_key,
            "max_retries": settings.default_max_retries,
            # Additional options
            "extract_tables": True,
            "save_figures": True,
            "figure_format": "png"
        }
        
        # Process document asynchronously
        result = await convert_single_pdf_to_markdown_async(**processing_params)
        
        # Convert to response format
        processing_result = ProcessingResult(
            pdf_path=request.pdf_path,
            success=True,
            markdown_path=str(result.markdown_path),
            figures_count=len(result.figures),
            tables_count=len(result.tables),
            duration=0.0,  # Duration not available in single processing
            attempts=1
        )
        
        logger.info(f"Single document processing completed: {request.pdf_path}")
        
        return SingleProcessResponse(
            status="completed",
            result=processing_result
        )
        
    except Exception as e:
        logger.error(f"Single document processing failed: {e}", exc_info=True)
        return SingleProcessResponse(
            status="failed",
            error=str(e)
        )

# Directory processing endpoint
@app.post("/api/v1/process/directory")
async def process_directory(
    directory_path: str,
    file_pattern: str = "*.pdf",
    output_path: str = None,
    max_concurrent: int = 5,
    enable_gemini: bool = False,
    settings: Settings = Depends(get_settings)
):
    """
    Process all PDF files in a directory.
    
    This endpoint scans a directory for PDF files and processes them all
    concurrently. Useful for batch processing entire document collections.
    """
    logger.info(f"Processing directory: {directory_path}")
    
    try:
        # Validate directory exists
        if not Path(directory_path).exists():
            raise HTTPException(
                status_code=404,
                detail=f"Directory not found: {directory_path}"
            )
        
        # Process directory asynchronously
        summary = await convert_directory_pdfs_to_markdown_async(
            directory_path=directory_path,
            file_pattern=file_pattern,
            output_path=output_path or settings.default_output_dir,
            max_concurrent=max_concurrent,
            enable_gemini=enable_gemini,
            gemini_api_key=settings.gemini_api_key,
            show_progress=False
        )
        
        logger.info(f"Directory processing completed: {directory_path}")
        
        return {
            "status": "completed",
            "directory": directory_path,
            "total_files": summary.get('total_files', 0),
            "successful": summary.get('successful', 0),
            "failed": summary.get('failed', 0),
            "success_rate": summary.get('success_rate', 0.0),
            "total_duration": summary.get('total_duration', 0.0)
        }
        
    except Exception as e:
        logger.error(f"Directory processing failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Directory processing failed: {str(e)}"
        )

# Background processing endpoint
@app.post("/api/v1/process/background")
async def process_background(
    request: BatchProcessRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
):
    """
    Process documents in the background.
    
    This endpoint starts document processing in the background and returns
    immediately. Useful for long-running processing tasks.
    """
    logger.info(f"Starting background processing for {len(request.pdf_paths)} documents")
    
    async def background_processing():
        """Background task for document processing."""
        try:
            results = await convert_pdf_batch_to_markdown_async(
                pdf_paths=request.pdf_paths,
                output_path=request.output_path or settings.default_output_dir,
                max_concurrent=request.max_concurrent,
                max_retries=request.max_retries,
                enable_gemini=request.enable_gemini,
                gemini_api_key=request.gemini_api_key or settings.gemini_api_key,
                show_progress=False
            )
            
            # Log results (in production, you might save to database)
            successful = sum(1 for r in results if r['success'])
            logger.info(f"Background processing completed: {successful}/{len(results)} successful")
            
        except Exception as e:
            logger.error(f"Background processing failed: {e}", exc_info=True)
    
    # Add background task
    background_tasks.add_task(background_processing)
    
    return {
        "status": "started",
        "message": "Background processing started",
        "total_documents": len(request.pdf_paths)
    }

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "Document Processing API",
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health"
    }

# Application startup event
@app.on_event("startup")
async def startup_event():
    """Application startup configuration."""
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Debug mode: {settings.debug}")
    
    # Create output directory if it doesn't exist
    Path(settings.default_output_dir).mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory: {settings.default_output_dir}")

# Application shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown cleanup."""
    logger.info("Shutting down Document Processing API")

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )
```

**Step 4: Create Requirements File (`requirements.txt`)**

```txt
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
python-multipart>=0.0.6
pydantic>=2.0.0
python-dotenv>=1.0.0

# Your document processing package
doc2md-conversion-engine

# Additional dependencies (if needed)
aiofiles>=23.0.0
```

**Step 5: Create Environment File (`.env`)**

```bash
# Application Configuration
APP_NAME="Document Processing API"
APP_VERSION="1.0.0"
DEBUG=false
LOG_LEVEL=INFO

# Server Configuration
HOST=0.0.0.0
PORT=8000

# Processing Configuration
DEFAULT_MAX_CONCURRENT=5
DEFAULT_MAX_RETRIES=3
DEFAULT_TIMEOUT=300
DEFAULT_OUTPUT_DIR=/tmp/processed_documents

# Gemini Configuration
GEMINI_API_KEY=your-gemini-api-key-here
```

### Advanced Features

**1. Authentication and Authorization:**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify API token."""
    if credentials.credentials != "your-secret-token":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    return credentials.credentials

# Add to endpoints
@app.post("/api/v1/process/batch")
async def process_batch(
    request: BatchProcessRequest,
    token: str = Depends(verify_token)
):
    # ... processing logic
```

**2. Rate Limiting:**

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/api/v1/process/batch")
@limiter.limit("10/minute")  # 10 requests per minute
async def process_batch(request: Request, batch_request: BatchProcessRequest):
    # ... processing logic
```

**3. Database Integration:**

```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Database setup
engine = create_async_engine("sqlite+aiosqlite:///./processing.db")
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# Use in endpoints
@app.post("/api/v1/process/batch")
async def process_batch(
    request: BatchProcessRequest,
    db: AsyncSession = Depends(get_db)
):
    # Save processing request to database
    # ... processing logic
```

### Production Deployment

**1. Using Docker:**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**2. Using Docker Compose:**

```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - DEFAULT_OUTPUT_DIR=/app/output
    volumes:
      - ./output:/app/output
    restart: unless-stopped
```

**3. Using Gunicorn with Uvicorn Workers:**

```bash
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Testing the API

**1. Start the Server:**

```bash
# Development
python main.py

# Production
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

**2. Test Endpoints:**

```bash
# Health check
curl http://localhost:8000/health

# Process single document
curl -X POST "http://localhost:8000/api/v1/process/single" \
  -H "Content-Type: application/json" \
  -d '{
    "pdf_path": "/path/to/document.pdf",
    "enable_gemini": true
  }'

# Process batch
curl -X POST "http://localhost:8000/api/v1/process/batch" \
  -H "Content-Type: application/json" \
  -d '{
    "pdf_paths": ["/path/to/doc1.pdf", "/path/to/doc2.pdf"],
    "enable_gemini": true,
    "max_concurrent": 5
  }'
```

**3. Interactive API Documentation:**

Visit `http://localhost:8000/docs` for interactive Swagger documentation.

## Chapter 6: Practical Examples

This chapter provides real-world examples and patterns for using the async API in various scenarios.

### Basic Document Processing

**Simple async processing with error handling:**

```python
import asyncio
import logging
from pathlib import Path
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown_async

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def process_documents_basic():
    """Basic document processing with comprehensive error handling."""
    
    # Define documents to process
    pdf_files = [
        "documents/clinical_guideline_1.pdf",
        "documents/clinical_guideline_2.pdf",
        "documents/research_paper.pdf"
    ]
    
    try:
        logger.info(f"Starting processing of {len(pdf_files)} documents")
        
        # Process documents with basic configuration
        results = await convert_pdf_batch_to_markdown_async(
            pdf_paths=pdf_files,
            output_path="/output/processed_docs",
            max_concurrent=3,                    # Process 3 documents at once
            max_retries=2,                       # Retry failed documents twice
            enable_gemini=True,                  # Enable AI figure analysis
            show_progress=True,                  # Show progress bar
            # Additional configuration
            extract_tables=True,                 # Extract tables
            save_figures=True,                   # Save figures
            figure_format="png"                  # PNG format for figures
        )
        
        # Process and display results
        successful_count = 0
        total_duration = 0.0
        
        logger.info("Processing Results:")
        logger.info("=" * 50)
        
        for i, result in enumerate(results, 1):
            filename = Path(result['pdf_path']).name
            
            if result['success']:
                successful_count += 1
                doc_result = result['result']
                total_duration += result['duration']
                
                logger.info(f"✓ {i}. {filename}")
                logger.info(f"   Markdown: {doc_result.markdown_path}")
                logger.info(f"   Figures: {len(doc_result.figures)}")
                logger.info(f"   Tables: {len(doc_result.tables)}")
                logger.info(f"   Duration: {result['duration']:.2f}s")
            else:
                logger.error(f"✗ {i}. {filename}")
                logger.error(f"   Error: {result['error']}")
                logger.error(f"   Attempts: {result['attempts']}")
        
        # Summary
        success_rate = (successful_count / len(results)) * 100
        logger.info("=" * 50)
        logger.info(f"Summary: {successful_count}/{len(results)} successful ({success_rate:.1f}%)")
        logger.info(f"Total Duration: {total_duration:.2f}s")
        
        return results
        
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        return []

# Run the example
if __name__ == "__main__":
    results = asyncio.run(process_documents_basic())
```

### Batch Processing with Progress

**Advanced batch processing with detailed progress tracking:**

```python
import asyncio
import time
from typing import List, Dict, Any
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown_async

class ProcessingMonitor:
    """Monitor processing progress and provide detailed reporting."""
    
    def __init__(self, total_documents: int):
        self.total_documents = total_documents
        self.start_time = time.time()
        self.completed = 0
        self.successful = 0
        self.failed = 0
        
    def update_progress(self, results: List[Dict[str, Any]]):
        """Update progress based on results."""
        self.completed = len(results)
        self.successful = sum(1 for r in results if r['success'])
        self.failed = self.completed - self.successful
        
        # Calculate progress percentage
        progress = (self.completed / self.total_documents) * 100
        
        # Calculate elapsed time and estimated remaining time
        elapsed = time.time() - self.start_time
        if self.completed > 0:
            avg_time_per_doc = elapsed / self.completed
            remaining_docs = self.total_documents - self.completed
            estimated_remaining = avg_time_per_doc * remaining_docs
        else:
            estimated_remaining = 0
        
        # Display progress
        print(f"\rProgress: {self.completed}/{self.total_documents} "
              f"({progress:.1f}%) | "
              f"✓ {self.successful} | ✗ {self.failed} | "
              f"Elapsed: {elapsed:.1f}s | "
              f"ETA: {estimated_remaining:.1f}s", end="", flush=True)
    
    def final_report(self, results: List[Dict[str, Any]]):
        """Display final processing report."""
        total_duration = time.time() - self.start_time
        success_rate = (self.successful / self.total_documents) * 100
        
        print(f"\n\nProcessing Complete!")
        print(f"=" * 60)
        print(f"Total Documents: {self.total_documents}")
        print(f"Successful: {self.successful}")
        print(f"Failed: {self.failed}")
        print(f"Success Rate: {success_rate:.1f}%")
        print(f"Total Duration: {total_duration:.2f}s")
        print(f"Average per Document: {total_duration/self.total_documents:.2f}s")
        print(f"=" * 60)

async def process_with_monitoring():
    """Process documents with detailed progress monitoring."""
    
    # Large list of documents to process
    pdf_files = [
        f"documents/guideline_{i:03d}.pdf" for i in range(1, 21)  # 20 documents
    ]
    
    # Create progress monitor
    monitor = ProcessingMonitor(len(pdf_files))
    
    try:
        print(f"Starting batch processing of {len(pdf_files)} documents...")
        print("Configuration: max_concurrent=5, enable_gemini=True")
        print("-" * 60)
        
        # Process documents with monitoring
        results = await convert_pdf_batch_to_markdown_async(
            pdf_paths=pdf_files,
            output_path="/output/batch_processed",
            max_concurrent=5,                    # Process 5 documents concurrently
            max_retries=3,                       # Retry failed documents 3 times
            enable_gemini=True,                  # Enable AI analysis
            show_progress=False,                 # We'll handle progress ourselves
            # Additional configuration for better performance
            enable_processor_pooling=True,       # Use processor pooling
            processor_pool_size=5,               # Pool size matches concurrency
            task_timeout_seconds=600,            # 10-minute timeout per document
            exponential_backoff=True             # Use exponential backoff for retries
        )
        
        # Update progress and display final report
        monitor.update_progress(results)
        monitor.final_report(results)
        
        # Detailed results analysis
        print("\nDetailed Results Analysis:")
        print("-" * 60)
        
        # Group results by success/failure
        successful_results = [r for r in results if r['success']]
        failed_results = [r for r in results if not r['success']]
        
        if successful_results:
            print(f"\nSuccessful Documents ({len(successful_results)}):")
            for result in successful_results:
                doc_result = result['result']
                print(f"  ✓ {Path(result['pdf_path']).name}")
                print(f"    Figures: {len(doc_result.figures)}, "
                      f"Tables: {len(doc_result.tables)}, "
                      f"Duration: {result['duration']:.2f}s")
        
        if failed_results:
            print(f"\nFailed Documents ({len(failed_results)}):")
            for result in failed_results:
                print(f"  ✗ {Path(result['pdf_path']).name}")
                print(f"    Error: {result['error']}")
                print(f"    Attempts: {result['attempts']}")
        
        return results
        
    except Exception as e:
        print(f"\nProcessing failed: {e}")
        return []

# Run the example
if __name__ == "__main__":
    results = asyncio.run(process_with_monitoring())
```

### Error Handling and Retries

**Robust error handling with custom retry strategies:**

```python
import asyncio
import logging
from typing import List, Dict, Any, Optional
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown_async
from doc2md_conversion_engine.exceptions import APIKeyError, ProcessingError

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

class DocumentProcessor:
    """Advanced document processor with robust error handling."""
    
    def __init__(self, max_retries: int = 3, retry_delay: float = 2.0):
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.processing_stats = {
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'retries_used': 0
        }
    
    async def process_with_retry(self, pdf_paths: List[str], **kwargs) -> List[Dict[str, Any]]:
        """Process documents with custom retry logic."""
        
        logger.info(f"Starting processing of {len(pdf_paths)} documents")
        logger.info(f"Retry configuration: max_retries={self.max_retries}, delay={self.retry_delay}s")
        
        # First attempt
        try:
            results = await convert_pdf_batch_to_markdown_async(
                pdf_paths=pdf_paths,
                max_retries=0,  # We'll handle retries manually
                **kwargs
            )
            
            # Check for failures and retry if needed
            failed_docs = [r for r in results if not r['success']]
            
            if failed_docs and self.max_retries > 0:
                logger.info(f"Found {len(failed_docs)} failed documents, attempting retries...")
                results = await self._retry_failed_documents(failed_docs, results, **kwargs)
            
            # Update statistics
            self._update_stats(results)
            self._log_final_stats()
            
            return results
            
        except APIKeyError as e:
            logger.error(f"API Key Error: {e.message}")
            raise
        except ProcessingError as e:
            logger.error(f"Processing Error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            raise
    
    async def _retry_failed_documents(
        self, 
        failed_docs: List[Dict[str, Any]], 
        all_results: List[Dict[str, Any]], 
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Retry failed documents with exponential backoff."""
        
        retry_count = 0
        remaining_failed = failed_docs.copy()
        
        while remaining_failed and retry_count < self.max_retries:
            retry_count += 1
            self.processing_stats['retries_used'] += 1
            
            # Calculate delay with exponential backoff
            delay = self.retry_delay * (2 ** (retry_count - 1))
            logger.info(f"Retry attempt {retry_count}/{self.max_retries} after {delay}s delay")
            
            await asyncio.sleep(delay)
            
            # Extract paths of failed documents
            failed_paths = [doc['pdf_path'] for doc in remaining_failed]
            
            try:
                # Retry failed documents
                retry_results = await convert_pdf_batch_to_markdown_async(
                    pdf_paths=failed_paths,
                    max_retries=0,  # No automatic retries
                    **kwargs
                )
                
                # Update results with retry outcomes
                for retry_result in retry_results:
                    # Find the corresponding result in all_results
                    for i, original_result in enumerate(all_results):
                        if original_result['pdf_path'] == retry_result['pdf_path']:
                            if retry_result['success']:
                                # Update successful retry
                                all_results[i] = retry_result
                                all_results[i]['attempts'] = original_result['attempts'] + 1
                                logger.info(f"✓ Retry successful: {Path(retry_result['pdf_path']).name}")
                            else:
                                # Update failed retry
                                all_results[i]['attempts'] += 1
                                all_results[i]['error'] = retry_result['error']
                                logger.warning(f"✗ Retry failed: {Path(retry_result['pdf_path']).name}")
                            break
                
                # Update remaining failed documents
                remaining_failed = [r for r in all_results if not r['success']]
                
                if not remaining_failed:
                    logger.info("All documents processed successfully after retries!")
                    break
                    
            except Exception as e:
                logger.error(f"Retry attempt {retry_count} failed: {e}")
                if retry_count >= self.max_retries:
                    logger.error("All retry attempts exhausted")
                    break
        
        return all_results
    
    def _update_stats(self, results: List[Dict[str, Any]]):
        """Update processing statistics."""
        self.processing_stats['total_processed'] = len(results)
        self.processing_stats['successful'] = sum(1 for r in results if r['success'])
        self.processing_stats['failed'] = len(results) - self.processing_stats['successful']
    
    def _log_final_stats(self):
        """Log final processing statistics."""
        stats = self.processing_stats
        success_rate = (stats['successful'] / stats['total_processed']) * 100 if stats['total_processed'] > 0 else 0
        
        logger.info("Processing Statistics:")
        logger.info(f"  Total Processed: {stats['total_processed']}")
        logger.info(f"  Successful: {stats['successful']}")
        logger.info(f"  Failed: {stats['failed']}")
        logger.info(f"  Success Rate: {success_rate:.1f}%")
        logger.info(f"  Retries Used: {stats['retries_used']}")

async def process_with_advanced_error_handling():
    """Process documents with advanced error handling and retry logic."""
    
    # Documents to process (some may fail)
    pdf_files = [
        "documents/valid_doc1.pdf",
        "documents/valid_doc2.pdf",
        "documents/corrupted_doc.pdf",  # This might fail
        "documents/large_doc.pdf",      # This might timeout
        "documents/valid_doc3.pdf"
    ]
    
    # Create processor with custom retry configuration
    processor = DocumentProcessor(
        max_retries=3,      # Retry failed documents up to 3 times
        retry_delay=1.0     # Start with 1 second delay
    )
    
    try:
        # Process documents with advanced error handling
        results = await processor.process_with_retry(
            pdf_paths=pdf_files,
            output_path="/output/error_handling_test",
            max_concurrent=2,                    # Lower concurrency for stability
            enable_gemini=True,                  # Enable AI analysis
            # Additional configuration for error handling
            task_timeout_seconds=300,            # 5-minute timeout
            enable_processor_pooling=True,       # Use processor pooling
            processor_pool_size=2,               # Match concurrency
            exponential_backoff=True             # Use exponential backoff
        )
        
        # Analyze results
        logger.info("\nFinal Results Analysis:")
        logger.info("=" * 50)
        
        for i, result in enumerate(results, 1):
            filename = Path(result['pdf_path']).name
            if result['success']:
                doc_result = result['result']
                logger.info(f"✓ {i}. {filename}")
                logger.info(f"   Figures: {len(doc_result.figures)}, "
                           f"Tables: {len(doc_result.tables)}")
                logger.info(f"   Attempts: {result['attempts']}")
            else:
                logger.error(f"✗ {i}. {filename}")
                logger.error(f"   Error: {result['error']}")
                logger.error(f"   Attempts: {result['attempts']}")
        
        return results
        
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        return []

# Run the example
if __name__ == "__main__":
    results = asyncio.run(process_with_advanced_error_handling())
```

### Custom Output Management

**Advanced output management with custom directory structures:**

```python
import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown_async

class OutputManager:
    """Manages output directory structure and file organization."""
    
    def __init__(self, base_output_dir: str):
        self.base_output_dir = Path(base_output_dir)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = self.base_output_dir / f"session_{self.session_id}"
        
    def setup_session_directory(self) -> Path:
        """Create session directory structure."""
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories
        (self.session_dir / "markdown").mkdir(exist_ok=True)
        (self.session_dir / "figures").mkdir(exist_ok=True)
        (self.session_dir / "tables").mkdir(exist_ok=True)
        (self.session_dir / "logs").mkdir(exist_ok=True)
        
        return self.session_dir
    
    def organize_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Organize processing results into structured output."""
        organized = {
            'session_id': self.session_id,
            'session_dir': str(self.session_dir),
            'total_documents': len(results),
            'successful': 0,
            'failed': 0,
            'documents': []
        }
        
        for result in results:
            doc_info = {
                'pdf_path': result['pdf_path'],
                'pdf_name': Path(result['pdf_path']).name,
                'success': result['success'],
                'duration': result['duration'],
                'attempts': result['attempts']
            }
            
            if result['success'] and result['result']:
                doc_result = result['result']
                doc_info.update({
                    'markdown_path': str(doc_result.markdown_path),
                    'figures_count': len(doc_result.figures),
                    'tables_count': len(doc_result.tables),
                    'figures': [str(f) for f in doc_result.figures],
                    'tables': [str(t) for t in doc_result.tables]
                })
                organized['successful'] += 1
            else:
                doc_info['error'] = result['error']
                organized['failed'] += 1
            
            organized['documents'].append(doc_info)
        
        return organized
    
    def create_summary_report(self, organized_results: Dict[str, Any]) -> Path:
        """Create a summary report of the processing session."""
        report_path = self.session_dir / "logs" / "processing_summary.txt"
        
        with open(report_path, 'w') as f:
            f.write("Document Processing Summary Report\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"Session ID: {organized_results['session_id']}\n")
            f.write(f"Session Directory: {organized_results['session_dir']}\n")
            f.write(f"Processing Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            f.write("Statistics:\n")
            f.write(f"  Total Documents: {organized_results['total_documents']}\n")
            f.write(f"  Successful: {organized_results['successful']}\n")
            f.write(f"  Failed: {organized_results['failed']}\n")
            f.write(f"  Success Rate: {(organized_results['successful']/organized_results['total_documents']*100):.1f}%\n\n")
            
            f.write("Document Details:\n")
            f.write("-" * 30 + "\n")
            
            for i, doc in enumerate(organized_results['documents'], 1):
                f.write(f"{i}. {doc['pdf_name']}\n")
                f.write(f"   Status: {'✓ Success' if doc['success'] else '✗ Failed'}\n")
                f.write(f"   Duration: {doc['duration']:.2f}s\n")
                f.write(f"   Attempts: {doc['attempts']}\n")
                
                if doc['success']:
                    f.write(f"   Figures: {doc['figures_count']}\n")
                    f.write(f"   Tables: {doc['tables_count']}\n")
                    f.write(f"   Markdown: {doc['markdown_path']}\n")
                else:
                    f.write(f"   Error: {doc['error']}\n")
                f.write("\n")
        
        return report_path

async def process_with_custom_output_management():
    """Process documents with custom output management and organization."""
    
    # Documents to process
    pdf_files = [
        "documents/clinical_guideline_1.pdf",
        "documents/clinical_guideline_2.pdf",
        "documents/research_paper.pdf",
        "documents/technical_specification.pdf"
    ]
    
    # Create output manager
    output_manager = OutputManager("/output/custom_processing")
    
    # Setup session directory
    session_dir = output_manager.setup_session_directory()
    print(f"Session directory created: {session_dir}")
    
    try:
        # Process documents
        results = await convert_pdf_batch_to_markdown_async(
            pdf_paths=pdf_files,
            output_path=str(session_dir),        # Use session directory
            max_concurrent=2,                    # Process 2 documents concurrently
            enable_gemini=True,                  # Enable AI analysis
            show_progress=True,                  # Show progress
            # Additional configuration
            extract_tables=True,                 # Extract tables
            save_figures=True,                   # Save figures
            figure_format="png",                 # PNG format
            enable_processor_pooling=True        # Use processor pooling
        )
        
        # Organize results
        organized_results = output_manager.organize_results(results)
        
        # Create summary report
        report_path = output_manager.create_summary_report(organized_results)
        
        # Display results
        print("\nProcessing Complete!")
        print("=" * 50)
        print(f"Session ID: {organized_results['session_id']}")
        print(f"Session Directory: {organized_results['session_dir']}")
        print(f"Total Documents: {organized_results['total_documents']}")
        print(f"Successful: {organized_results['successful']}")
        print(f"Failed: {organized_results['failed']}")
        print(f"Success Rate: {(organized_results['successful']/organized_results['total_documents']*100):.1f}%")
        print(f"Summary Report: {report_path}")
        
        # Show individual results
        print("\nIndividual Results:")
        print("-" * 30)
        for doc in organized_results['documents']:
            status = "✓" if doc['success'] else "✗"
            print(f"{status} {doc['pdf_name']}")
            if doc['success']:
                print(f"  Figures: {doc['figures_count']}, Tables: {doc['tables_count']}")
                print(f"  Duration: {doc['duration']:.2f}s")
            else:
                print(f"  Error: {doc['error']}")
        
        return organized_results
        
    except Exception as e:
        print(f"Processing failed: {e}")
        return None

# Run the example
if __name__ == "__main__":
    results = asyncio.run(process_with_custom_output_management())
```

## Chapter 7: Performance Optimization

This chapter covers strategies for optimizing the performance of your async document processing applications.

### Concurrency Tuning

**Understanding Concurrency Parameters:**

```python
# Optimal concurrency depends on your system resources
async def optimize_concurrency():
    """Demonstrate different concurrency configurations."""
    
    # For CPU-bound tasks (document processing)
    cpu_optimized = await convert_pdf_batch_to_markdown_async(
        pdf_paths=pdf_files,
        max_concurrent=4,                    # 4x CPU cores
        max_concurrent_processors=2,         # 2x CPU cores
        enable_processor_pooling=True,       # Essential for performance
        processor_pool_size=4                # Match max_concurrent
    )
    
    # For I/O-bound tasks (file operations, API calls)
    io_optimized = await convert_pdf_batch_to_markdown_async(
        pdf_paths=pdf_files,
        max_concurrent=10,                   # Higher for I/O
        max_concurrent_processors=4,         # Lower for processors
        enable_processor_pooling=True,
        processor_pool_size=4
    )
    
    # For memory-constrained environments
    memory_optimized = await convert_pdf_batch_to_markdown_async(
        pdf_paths=pdf_files,
        max_concurrent=2,                    # Lower concurrency
        max_concurrent_processors=1,         # Single processor
        enable_processor_pooling=True,
        processor_pool_size=2
    )
```

**Dynamic Concurrency Adjustment:**

```python
import psutil
import asyncio
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown_async

class AdaptiveConcurrencyManager:
    """Dynamically adjust concurrency based on system resources."""
    
    def __init__(self):
        self.cpu_count = psutil.cpu_count()
        self.memory_gb = psutil.virtual_memory().total / (1024**3)
        
    def get_optimal_concurrency(self, document_count: int) -> dict:
        """Calculate optimal concurrency settings."""
        
        # Base concurrency on CPU cores
        base_concurrent = min(self.cpu_count, document_count)
        
        # Adjust based on memory
        if self.memory_gb < 4:
            # Low memory - reduce concurrency
            max_concurrent = max(1, base_concurrent // 2)
            processor_pool_size = max(1, base_concurrent // 2)
        elif self.memory_gb < 8:
            # Medium memory - moderate concurrency
            max_concurrent = base_concurrent
            processor_pool_size = max(2, base_concurrent // 2)
        else:
            # High memory - full concurrency
            max_concurrent = base_concurrent
            processor_pool_size = base_concurrent
        
        return {
            'max_concurrent': max_concurrent,
            'max_concurrent_processors': min(processor_pool_size, max_concurrent),
            'processor_pool_size': processor_pool_size,
            'enable_processor_pooling': True
        }
    
    async def process_with_adaptive_concurrency(self, pdf_paths: list, **kwargs):
        """Process documents with adaptive concurrency."""
        
        # Get optimal settings
        optimal_settings = self.get_optimal_concurrency(len(pdf_paths))
        
        print(f"System Resources: {self.cpu_count} CPUs, {self.memory_gb:.1f}GB RAM")
        print(f"Optimal Settings: {optimal_settings}")
        
        # Process with optimal settings
        results = await convert_pdf_batch_to_markdown_async(
            pdf_paths=pdf_paths,
            **optimal_settings,
            **kwargs
        )
        
        return results

# Usage example
async def adaptive_processing_example():
    """Example of adaptive concurrency processing."""
    
    pdf_files = [f"doc_{i}.pdf" for i in range(1, 21)]  # 20 documents
    
    manager = AdaptiveConcurrencyManager()
    results = await manager.process_with_adaptive_concurrency(
        pdf_paths=pdf_files,
        enable_gemini=True,
        show_progress=True
    )
    
    return results
```

### Resource Management

**Memory Optimization:**

```python
import gc
import asyncio
from typing import List, Dict, Any
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown_async

class MemoryOptimizedProcessor:
    """Memory-optimized document processor."""
    
    def __init__(self, batch_size: int = 5):
        self.batch_size = batch_size
        
    async def process_large_dataset(self, pdf_paths: List[str], **kwargs) -> List[Dict[str, Any]]:
        """Process large datasets in memory-efficient batches."""
        
        all_results = []
        total_docs = len(pdf_paths)
        
        print(f"Processing {total_docs} documents in batches of {self.batch_size}")
        
        # Process in batches to manage memory
        for i in range(0, total_docs, self.batch_size):
            batch_paths = pdf_paths[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            total_batches = (total_docs + self.batch_size - 1) // self.batch_size
            
            print(f"Processing batch {batch_num}/{total_batches} ({len(batch_paths)} documents)")
            
            try:
                # Process current batch
                batch_results = await convert_pdf_batch_to_markdown_async(
                    pdf_paths=batch_paths,
                    max_concurrent=min(2, len(batch_paths)),  # Limit concurrency
                    enable_processor_pooling=True,
                    processor_pool_size=2,  # Small pool for memory efficiency
                    **kwargs
                )
                
                all_results.extend(batch_results)
                
                # Force garbage collection after each batch
                gc.collect()
                
                print(f"  Batch {batch_num} complete: {sum(1 for r in batch_results if r['success'])}/{len(batch_results)} successful")
                
            except Exception as e:
                print(f"  Batch {batch_num} failed: {e}")
                # Add failed results for this batch
                for path in batch_paths:
                    all_results.append({
                        'pdf_path': path,
                        'success': False,
                        'error': str(e),
                        'attempts': 1,
                        'duration': 0.0
                    })
        
        return all_results

# Usage example
async def memory_optimized_processing():
    """Example of memory-optimized processing."""
    
    # Large list of documents
    pdf_files = [f"large_dataset/doc_{i:04d}.pdf" for i in range(1, 101)]  # 100 documents
    
    processor = MemoryOptimizedProcessor(batch_size=10)  # Process 10 at a time
    
    results = await processor.process_large_dataset(
        pdf_paths=pdf_files,
        enable_gemini=True,
        output_path="/output/large_dataset"
    )
    
    successful = sum(1 for r in results if r['success'])
    print(f"Final Results: {successful}/{len(results)} successful")
    
    return results
```

**CPU Optimization:**

```python
import asyncio
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown_async

class CPUOptimizedProcessor:
    """CPU-optimized processor using multiprocessing."""
    
    def __init__(self, max_workers: int = None):
        self.max_workers = max_workers or multiprocessing.cpu_count()
        
    async def process_with_multiprocessing(self, pdf_paths: list, **kwargs) -> list:
        """Process documents using multiprocessing for CPU-intensive tasks."""
        
        # Split documents into chunks for each process
        chunk_size = len(pdf_paths) // self.max_workers
        chunks = [pdf_paths[i:i + chunk_size] for i in range(0, len(pdf_paths), chunk_size)]
        
        print(f"Processing {len(pdf_paths)} documents using {self.max_workers} processes")
        print(f"Chunk sizes: {[len(chunk) for chunk in chunks]}")
        
        # Create process pool
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit tasks to process pool
            tasks = []
            for chunk in chunks:
                if chunk:  # Skip empty chunks
                    task = executor.submit(self._process_chunk, chunk, **kwargs)
                    tasks.append(task)
            
            # Wait for all tasks to complete
            results = []
            for task in asyncio.as_completed([asyncio.wrap_future(t) for t in tasks]):
                chunk_results = await task
                results.extend(chunk_results)
        
        return results
    
    def _process_chunk(self, pdf_paths: list, **kwargs) -> list:
        """Process a chunk of documents (runs in separate process)."""
        import asyncio
        from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown_async
        
        # Run async function in new event loop
        return asyncio.run(convert_pdf_batch_to_markdown_async(
            pdf_paths=pdf_paths,
            **kwargs
        ))

# Usage example
async def cpu_optimized_processing():
    """Example of CPU-optimized processing."""
    
    pdf_files = [f"cpu_intensive/doc_{i}.pdf" for i in range(1, 51)]  # 50 documents
    
    processor = CPUOptimizedProcessor(max_workers=4)  # Use 4 processes
    
    results = await processor.process_with_multiprocessing(
        pdf_paths=pdf_files,
        enable_gemini=True,
        max_concurrent=2,  # Per process
        enable_processor_pooling=True
    )
    
    return results
```

### Memory Optimization

**Advanced Memory Management:**

```python
import tracemalloc
import asyncio
from typing import List, Dict, Any
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown_async

class MemoryProfiler:
    """Profile and optimize memory usage during processing."""
    
    def __init__(self):
        self.memory_snapshots = []
        
    def start_profiling(self):
        """Start memory profiling."""
        tracemalloc.start()
        print("Memory profiling started")
    
    def take_snapshot(self, label: str):
        """Take a memory snapshot."""
        snapshot = tracemalloc.take_snapshot()
        self.memory_snapshots.append((label, snapshot))
        
        # Get current memory usage
        current, peak = tracemalloc.get_traced_memory()
        print(f"Memory snapshot '{label}': {current / 1024 / 1024:.1f}MB current, {peak / 1024 / 1024:.1f}MB peak")
    
    def stop_profiling(self):
        """Stop memory profiling and display results."""
        tracemalloc.stop()
        
        print("\nMemory Profiling Results:")
        print("=" * 50)
        
        for i, (label, snapshot) in enumerate(self.memory_snapshots):
            if i > 0:
                prev_snapshot = self.memory_snapshots[i-1][1]
                top_stats = snapshot.compare_to(prev_snapshot, 'lineno')
                
                print(f"\n{label} (vs previous):")
                for stat in top_stats[:5]:  # Top 5 differences
                    print(f"  {stat}")
    
    async def process_with_memory_profiling(self, pdf_paths: List[str], **kwargs) -> List[Dict[str, Any]]:
        """Process documents with memory profiling."""
        
        self.start_profiling()
        self.take_snapshot("Start")
        
        try:
            # Process documents
            results = await convert_pdf_batch_to_markdown_async(
                pdf_paths=pdf_paths,
                **kwargs
            )
            
            self.take_snapshot("After Processing")
            
            # Process results (this might use more memory)
            successful_count = sum(1 for r in results if r['success'])
            self.take_snapshot("After Result Processing")
            
            print(f"Processing complete: {successful_count}/{len(results)} successful")
            
            return results
            
        finally:
            self.take_snapshot("End")
            self.stop_profiling()

# Usage example
async def memory_profiling_example():
    """Example of memory profiling during processing."""
    
    pdf_files = [f"memory_test/doc_{i}.pdf" for i in range(1, 11)]  # 10 documents
    
    profiler = MemoryProfiler()
    
    results = await profiler.process_with_memory_profiling(
        pdf_paths=pdf_files,
        enable_gemini=True,
        max_concurrent=3,
        enable_processor_pooling=True
    )
    
    return results
```

## Chapter 8: Troubleshooting

This chapter covers common issues and their solutions when using the async API.

### Common Issues

**1. Event Loop Issues:**

```python
# Problem: RuntimeError: Event loop is closed
# Solution: Always use asyncio.run() for top-level async calls

# Wrong
def main():
    results = await convert_pdf_batch_to_markdown_async(...)  # Error!

# Correct
async def main():
    results = await convert_pdf_batch_to_markdown_async(...)  # OK

if __name__ == "__main__":
    asyncio.run(main())  # OK

# Or use asyncio.run() directly
if __name__ == "__main__":
    results = asyncio.run(convert_pdf_batch_to_markdown_async(...))  # OK
```

**2. API Key Issues:**

```python
# Problem: APIKeyError: Gemini API key required
# Solution: Set environment variable or pass explicitly

import os

# Option 1: Environment variable (recommended)
os.environ['GEMINI_API_KEY'] = 'your-gemini-api-key'

# Option 2: Pass explicitly
results = await convert_pdf_batch_to_markdown_async(
    pdf_paths=paths,
    enable_gemini=True,
    gemini_api_key='your-gemini-api-key'
)

# Option 3: Check if key is set
if not os.getenv('GEMINI_API_KEY'):
    print("Warning: GEMINI_API_KEY not set. Gemini features will be disabled.")
    results = await convert_pdf_batch_to_markdown_async(
        pdf_paths=paths,
        enable_gemini=False  # Disable Gemini
    )
```

**3. Import Issues:**

```python
# Problem: ImportError: cannot import name 'convert_pdf_batch_to_markdown_async'
# Solution: Check import path and package installation

# Correct import
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown_async

# Alternative import
from doc2md_conversion_engine import convert_pdf_batch_to_markdown_async

# Check if package is installed
try:
    import doc2md_conversion_engine
    print(f"Package version: {doc2md_conversion_engine.__version__}")
except ImportError:
    print("Package not installed. Run: pip install doc2md-conversion-engine")
```

**4. Configuration Issues:**

```python
# Problem: Invalid configuration parameters
# Solution: Use proper configuration classes

from doc2md_conversion_engine.orchestration.configuration.batch_configuration import BatchConfiguration
from doc2md_conversion_engine.models.config import DocumentProcessingConfig

# Create proper configuration
batch_config = BatchConfiguration(
    max_concurrent_tasks=5,
    enable_processor_pooling=True
)

doc_config = DocumentProcessingConfig(
    enable_gemini=True,
    extract_tables=True
)

# Use with processing
results = await convert_pdf_batch_to_markdown_async(
    pdf_paths=paths,
    **batch_config.__dict__,
    **doc_config.__dict__
)
```

### Debugging Tips

**1. Enable Detailed Logging:**

```python
import logging

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)

# Reduce noise from external libraries
for logger_name in ['pdfminer', 'PIL', 'urllib3']:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

# Your processing code
results = await convert_pdf_batch_to_markdown_async(...)
```

**2. Test with Single Document:**

```python
# Test with single document first
async def debug_single_document():
    try:
        result = await convert_single_pdf_to_markdown_async(
            pdf_path="test_document.pdf",
            enable_gemini=True,
            show_progress=True
        )
        print("Single document processing successful")
        return result
    except Exception as e:
        print(f"Single document processing failed: {e}")
        import traceback
        traceback.print_exc()
        return None

# Then test with batch
async def debug_batch_processing():
    single_result = await debug_single_document()
    if single_result:
        # Single document works, try batch
        results = await convert_pdf_batch_to_markdown_async(
            pdf_paths=["test_document.pdf"],
            enable_gemini=True
        )
        print("Batch processing successful")
```

**3. Check System Resources:**

```python
import psutil
import torch

def check_system_resources():
    """Check system resources and configuration."""
    
    print("System Resources:")
    print(f"  CPU Cores: {psutil.cpu_count()}")
    print(f"  Memory: {psutil.virtual_memory().total / (1024**3):.1f}GB")
    print(f"  Available Memory: {psutil.virtual_memory().available / (1024**3):.1f}GB")
    
    print("\nPyTorch Configuration:")
    print(f"  PyTorch Version: {torch.__version__}")
    print(f"  CUDA Available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"  CUDA Devices: {torch.cuda.device_count()}")
        print(f"  Current Device: {torch.cuda.current_device()}")
    
    print("\nPython Environment:")
    print(f"  Python Version: {sys.version}")
    print(f"  Platform: {sys.platform}")

# Run before processing
check_system_resources()
```

### Performance Issues

**1. Slow Processing:**

```python
# Check if GPU acceleration is working
async def check_gpu_acceleration():
    """Verify GPU acceleration is working."""
    
    # Test with small document
    result = await convert_single_pdf_to_markdown_async(
        pdf_path="small_test.pdf",
        enable_gemini=False,  # Disable Gemini for speed test
        show_progress=True
    )
    
    print(f"Processing time: {result.duration:.2f}s")
    
    # Check logs for GPU usage
    # Look for: "Using CUDA device: cuda:0" or "Using Apple Silicon MPS"
```

**2. Memory Issues:**

```python
# Monitor memory usage during processing
import psutil
import asyncio

async def monitor_memory_usage():
    """Monitor memory usage during processing."""
    
    process = psutil.Process()
    
    def log_memory():
        memory_info = process.memory_info()
        print(f"Memory usage: {memory_info.rss / 1024 / 1024:.1f}MB")
    
    # Log memory before processing
    log_memory()
    
    # Process documents
    results = await convert_pdf_batch_to_markdown_async(
        pdf_paths=pdf_files,
        max_concurrent=2,  # Reduce concurrency if memory issues
        enable_processor_pooling=True
    )
    
    # Log memory after processing
    log_memory()
    
    return results
```

**3. Concurrency Issues:**

```python
# Test different concurrency levels
async def test_concurrency_levels():
    """Test different concurrency levels to find optimal setting."""
    
    pdf_files = ["test1.pdf", "test2.pdf", "test3.pdf", "test4.pdf", "test5.pdf"]
    
    concurrency_levels = [1, 2, 3, 4, 5]
    results = {}
    
    for level in concurrency_levels:
        print(f"Testing concurrency level: {level}")
        
        start_time = time.time()
        try:
            batch_results = await convert_pdf_batch_to_markdown_async(
                pdf_paths=pdf_files,
                max_concurrent=level,
                enable_processor_pooling=True,
                processor_pool_size=level
            )
            
            duration = time.time() - start_time
            successful = sum(1 for r in batch_results if r['success'])
            
            results[level] = {
                'duration': duration,
                'successful': successful,
                'throughput': successful / duration
            }
            
            print(f"  Duration: {duration:.2f}s, Successful: {successful}, Throughput: {successful/duration:.2f} docs/s")
            
        except Exception as e:
            print(f"  Failed: {e}")
            results[level] = {'error': str(e)}
    
    # Find optimal level
    best_level = max(
        [k for k, v in results.items() if 'error' not in v],
        key=lambda k: results[k]['throughput']
    )
    
    print(f"Optimal concurrency level: {best_level}")
    return results
```

## Chapter 9: Migration Guide

This chapter helps you migrate from synchronous to asynchronous processing.

### From Sync to Async

**1. Update Imports:**

```python
# Old (sync)
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown

# New (async)
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown_async
```

**2. Update Function Calls:**

```python
# Old (sync)
def process_documents():
    results = convert_pdf_batch_to_markdown(
        pdf_paths=["doc1.pdf", "doc2.pdf"],
        enable_gemini=True
    )
    return results

# New (async)
async def process_documents():
    results = await convert_pdf_batch_to_markdown_async(
        pdf_paths=["doc1.pdf", "doc2.pdf"],
        enable_gemini=True
    )
    return results
```

**3. Update Main Execution:**

```python
# Old (sync)
if __name__ == "__main__":
    results = process_documents()

# New (async)
if __name__ == "__main__":
    results = asyncio.run(process_documents())
```

### Upgrading Existing Code

**1. Gradual Migration:**

```python
# Step 1: Create async wrapper
async def async_wrapper(sync_function, *args, **kwargs):
    """Wrap sync function in async context."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sync_function, *args, **kwargs)

# Step 2: Use wrapper during migration
async def migrated_processing():
    # Old sync code wrapped in async
    results = await async_wrapper(
        convert_pdf_batch_to_markdown,
        pdf_paths=["doc1.pdf", "doc2.pdf"],
        enable_gemini=True
    )
    return results

# Step 3: Replace with native async
async def fully_migrated_processing():
    # New async code
    results = await convert_pdf_batch_to_markdown_async(
        pdf_paths=["doc1.pdf", "doc2.pdf"],
        enable_gemini=True
    )
    return results
```

**2. Hybrid Approach:**

```python
# Mix sync and async as needed
def sync_processing():
    """Sync processing for simple cases."""
    return convert_pdf_batch_to_markdown(
        pdf_paths=["doc1.pdf", "doc2.pdf"],
        enable_gemini=True
    )

async def async_processing():
    """Async processing for complex cases."""
    return await convert_pdf_batch_to_markdown_async(
        pdf_paths=["doc1.pdf", "doc2.pdf"],
        enable_gemini=True,
        max_concurrent=5
    )

# Use appropriate method based on context
if simple_case:
    results = sync_processing()
else:
    results = await async_processing()
```

## Support and Resources

For additional help and resources:

- **Example Scripts**: Check `example_pdf2md_conversion_async_api.py` for working examples
- **Documentation**: See module documentation in `doc2md_conversion_engine/orchestration/`
- **Issues**: Report issues on the project repository
- **Community**: Join discussions in project forums

## License

See project LICENSE file for details.
