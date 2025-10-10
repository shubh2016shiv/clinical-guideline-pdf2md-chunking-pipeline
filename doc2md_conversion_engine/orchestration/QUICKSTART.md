# Orchestration Module - Quick Start Guide

Get started with document processing orchestration in under 5 minutes.

## Installation

The orchestration module is part of the `document_processing_engine` package. No additional installation needed if you have the main project set up.

## Simplest Usage (3 Lines)

Process a single document:

```python
from doc2md_conversion_engine.orchestration import convert_single_pdf_to_markdown

result = convert_single_pdf_to_markdown("/path/to/document.pdf")
print(f"Output: {result.markdown_path}")
```

## Batch Processing (5 Lines)

Process multiple documents:

```python
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown

pdf_files = ["/data/doc1.pdf", "/data/doc2.pdf", "/data/doc3.pdf"]
results = convert_pdf_batch_to_markdown(pdf_files, max_concurrent=5)

print(f"Processed {len(results)} documents")
```

## Directory Processing (4 Lines)

Process all PDFs in a directory:

```python
from doc2md_conversion_engine.orchestration import convert_directory_pdfs_to_markdown

summary = convert_directory_pdfs_to_markdown("/data/pdfs/", max_concurrent=10)
print(f"Success rate: {summary['success_rate']:.1f}%")
```

## Common Scenarios

### High-Throughput Processing

For processing many documents quickly:

```python
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown

results = convert_pdf_batch_to_markdown(
    pdf_paths=my_pdf_list,
    max_concurrent=20,  # High concurrency
    enable_processor_pooling=True,  # Reuse processors
    processor_pool_size=10,  # Pool size
    show_progress=True  # Show progress bar
)
```

### Fault-Tolerant Processing

For unreliable documents or networks:

```python
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown

results = convert_pdf_batch_to_markdown(
    pdf_paths=my_pdf_list,
    max_retries=5,  # Retry up to 5 times
    exponential_backoff=True,  # Increase delay between retries
    continue_on_error=True  # Don't stop on failures
)
```

### Custom Configuration

For fine-grained control:

```python
from doc2md_conversion_engine.orchestration import (
    OrchestrationClient,
    BatchConfiguration
)

# Configure
config = BatchConfiguration(
    max_concurrent_tasks=10,
    max_retries_per_task=3,
    enable_processor_pooling=True
)

# Process with context manager
with OrchestrationClient(batch_config=config) as client:
    results = client.orchestrate_document_batch(my_pdf_list)
    metrics = client.get_orchestration_metrics()
    print(f"Success rate: {metrics['success_rate']:.1f}%")
```

## Async Usage

For async frameworks (FastAPI, etc.):

```python
from doc2md_conversion_engine.orchestration import process_documents_async


async def process_batch():
    results = await process_documents_async(
        pdf_paths=my_pdf_list,
        max_concurrent=20  # Even higher concurrency for async
    )
    return results


# In async context
import asyncio

results = asyncio.run(process_batch())
```

## Checking Results

All functions return structured results:

```python
results = process_documents(pdf_paths)

for result in results:
    if result['success']:
        print(f"✓ {result['pdf_path']}")
        print(f"  Output: {result['result'].markdown_path}")
        print(f"  Duration: {result['duration']:.2f}s")
    else:
        print(f"✗ {result['pdf_path']}")
        print(f"  Error: {result['error']}")
```

## Common Parameters

All processing functions accept these common parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_concurrent` | int | 5 | Maximum parallel tasks |
| `max_retries` | int | 3 | Retry attempts per document |
| `show_progress` | bool | True | Show progress bar |
| `output_path` | str | None | Output directory |

## Next Steps

- Read the full [README.md](README.md) for detailed documentation
- Check [examples/](examples/) for complete working examples
- Explore configuration options in [BatchConfiguration](configuration/batch_configuration.py)

## Need Help?

1. Check the [README.md](README.md) for comprehensive documentation
2. Run the examples in `examples/` directory
3. Review docstrings in the code (all functions are documented)

## Common Issues

**Import Error**: Make sure you're in the project root directory

**No progress bar**: Set `show_progress=True` in function call

**Too slow**: Increase `max_concurrent` parameter

**Too many failures**: Increase `max_retries` and enable `exponential_backoff`

**Memory issues**: Decrease `max_concurrent` or disable `enable_processor_pooling`

## That's It!

You're ready to start processing documents. The module handles all complexity internally - just pass your PDF paths and optional configuration.

For production use, read the full README and explore the configuration options to optimize for your specific use case.




