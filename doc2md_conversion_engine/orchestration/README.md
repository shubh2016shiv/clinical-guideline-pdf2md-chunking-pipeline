# Orchestration Module

A comprehensive orchestration framework for document processing with fault tolerance, scalability, and performance optimization.

## Overview

The orchestration module provides a robust framework for processing PDF documents with features including:

- **Fault Tolerance**: Circuit breaker pattern, automatic retries with exponential backoff
- **Scalability**: Concurrent processing with configurable parallelism
- **Resource Management**: Processor pooling for efficient resource usage
- **Performance Tracking**: Comprehensive metrics collection and reporting
- **Flexible APIs**: Simple functions, async operations, and object-oriented client

## Architecture

### Package Structure

```
orchestration/
├── models/                      # Data models
│   ├── processing_task.py      # Task model with lifecycle tracking
│   └── task_status.py          # Task status enumeration
│
├── configuration/              # Configuration schemas
│   ├── batch_configuration.py  # Batch processing config
│   └── orchestration_settings.py # System-wide settings
│
├── resilience/                 # Fault tolerance components
│   ├── circuit_breaker.py     # Circuit breaker pattern
│   ├── retry_handler.py       # Retry logic with backoff
│   └── resource_pool.py       # Processor pooling
│
├── metrics/                    # Performance tracking
│   └── performance_tracker.py # Metrics collection and reporting
│
├── adapters/                   # External integration adapters
│   ├── simple_api.py          # Function-based sync API
│   └── async_api.py           # Function-based async API
│
├── task_manager.py            # Individual task execution
├── batch_processor.py         # Batch coordination
├── orchestration_client.py    # Main client interface
└── examples/                   # Usage examples
    ├── example_simple_api.py
    ├── example_async_api.py
    └── example_client_usage.py
```

### Component Responsibilities

1. **OrchestrationClient**: Main entry point, composes all components
2. **TaskManager**: Manages individual task execution and retry logic
3. **BatchProcessor**: Coordinates parallel execution of multiple tasks
4. **CircuitBreaker**: Prevents cascading failures
5. **RetryHandler**: Implements retry strategies with backoff
6. **ProcessorPool**: Maintains pool of processors for reuse
7. **PerformanceTracker**: Collects and reports performance metrics

## Usage

### 1. Simple API (Easiest)

For straightforward document processing without managing objects:

```python
from doc2md_conversion_engine.orchestration import convert_single_pdf_to_markdown

# Process single document
result = convert_single_pdf_to_markdown("/data/document.pdf")
print(f"Output: {result.markdown_path}")
```

**Batch Processing:**

```python
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown

# Process multiple documents
paths = ["/data/doc1.pdf", "/data/doc2.pdf", "/data/doc3.pdf"]
results = convert_pdf_batch_to_markdown(
    pdf_paths=paths,
    max_concurrent=5,
    max_retries=3,
    show_progress=True
)

# Check results
successful = [r for r in results if r['success']]
print(f"Processed {len(successful)}/{len(results)} documents")
```

**Directory Processing:**

```python
from doc2md_conversion_engine.orchestration import convert_directory_pdfs_to_markdown

# Process all PDFs in directory
summary = convert_directory_pdfs_to_markdown(
    directory_path="/data/pdfs/",
    max_concurrent=10
)

print(f"Success rate: {summary['success_rate']:.1f}%")
```

### 2. Async API (High Performance)

For async frameworks and non-blocking operations:

```python
from doc2md_conversion_engine.orchestration import process_document_async


# In async context
async def main():
    result = await process_document_async("/data/document.pdf")
    print(f"Output: {result.markdown_path}")


import asyncio

asyncio.run(main())
```

**Async Batch Processing:**

```python
from doc2md_conversion_engine.orchestration import process_documents_async


async def main():
    paths = ["/data/doc1.pdf", "/data/doc2.pdf"]
    results = await process_documents_async(
        pdf_paths=paths,
        max_concurrent=10  # Higher concurrency for async
    )

    successful = [r for r in results if r['success']]
    print(f"Processed {len(successful)}/{len(results)}")


asyncio.run(main())
```

**Concurrent Batches:**

```python
from doc2md_conversion_engine.orchestration import process_concurrent_batches


async def main():
    batch1 = ["/data/batch1/doc1.pdf", "/data/batch1/doc2.pdf"]
    batch2 = ["/data/batch2/doc1.pdf", "/data/batch2/doc2.pdf"]

    # Process multiple batches concurrently
    results = await process_concurrent_batches(
        batch_paths=[batch1, batch2],
        max_concurrent_per_batch=5
    )


asyncio.run(main())
```

### 3. Client API (Full Control)

For applications needing fine-grained control:

```python
from doc2md_conversion_engine.orchestration import (
    OrchestrationClient,
    BatchConfiguration
)

# Create custom configuration
config = BatchConfiguration(
    max_concurrent_tasks=10,
    max_retries_per_task=5,
    enable_processor_pooling=True,
    processor_pool_size=5,
    exponential_backoff=True
)

# Use context manager for automatic cleanup
with OrchestrationClient(batch_config=config) as client:
    # Process documents
    results = client.orchestrate_document_batch(["/data/doc1.pdf", "/data/doc2.pdf"])

    # Get metrics
    metrics = client.get_orchestration_metrics()
    print(f"Success rate: {metrics['success_rate']:.1f}%")
```

## Configuration

### BatchConfiguration

Controls batch processing behavior:

```python
from doc2md_conversion_engine.orchestration import BatchConfiguration

config = BatchConfiguration(
    # Concurrency
    max_concurrent_tasks=5,  # Max parallel tasks
    max_concurrent_processors=3,  # Max processor instances

    # Retries
    enable_retries=True,
    max_retries_per_task=3,  # Retries per task
    retry_delay_seconds=2.0,  # Base delay between retries
    exponential_backoff=True,  # Double delay each retry

    # Performance
    enable_processor_pooling=True,  # Reuse processors
    processor_pool_size=3,  # Pool size
    task_timeout_seconds=600.0,  # Task timeout (10 min)

    # Fault Tolerance
    continue_on_error=True,  # Continue batch on failures
    circuit_breaker_threshold=5,  # Failures before circuit opens
    circuit_breaker_timeout=60.0,  # Seconds before circuit resets

    # Progress
    enable_progress_reporting=True,  # Show progress bars
    log_level="INFO"  # Logging verbosity
)
```

### OrchestrationSettings

System-wide settings:

```python
from doc2md_conversion_engine.orchestration import OrchestrationSettings

settings = OrchestrationSettings(
    enable_metrics_collection=True,
    default_output_directory="/data/processed",
    cleanup_on_shutdown=True,
    max_queue_size=10000
)
```

## Features

### Fault Tolerance

**Circuit Breaker**: Automatically opens after threshold failures, preventing cascading failures

```python
config = BatchConfiguration(
    circuit_breaker_threshold=5,  # Open after 5 failures
    circuit_breaker_timeout=60.0  # Reset after 60 seconds
)
```

**Automatic Retries**: Configurable retry logic with exponential backoff

```python
config = BatchConfiguration(
    max_retries_per_task=3,
    retry_delay_seconds=2.0,
    exponential_backoff=True  # Delays: 2s, 4s, 8s
)
```

### Performance Optimization

**Processor Pooling**: Reuse processor instances to reduce initialization overhead

```python
config = BatchConfiguration(
    enable_processor_pooling=True,
    processor_pool_size=5  # Maintain 5 warm processors
)
```

**Concurrent Processing**: Process multiple documents in parallel

```python
config = BatchConfiguration(
    max_concurrent_tasks=10  # Process up to 10 documents at once
)
```

### Metrics and Monitoring

Track performance metrics during processing:

```python
with OrchestrationClient() as client:
    results = client.convert_pdf_batch_to_markdown(pdf_paths)

    # Get comprehensive metrics
    metrics = client.get_orchestration_metrics()
    print(f"Total tasks: {metrics['total_tasks']}")
    print(f"Success rate: {metrics['success_rate']:.1f}%")
    print(f"Avg time: {metrics['average_processing_time']:.2f}s")
    print(f"Throughput: {metrics['throughput_tasks_per_second']:.2f} tasks/s")
```

## Integration Examples

### Using in External Modules

**Option 1: Simple import and use**

```python
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown


def process_clinical_guidelines(pdf_paths: List[str]):
    """Process clinical guideline PDFs."""
    return convert_pdf_batch_to_markdown(
        pdf_paths=pdf_paths,
        max_concurrent=5,
        show_progress=True
    )
```

**Option 2: Custom client**

```python
from doc2md_conversion_engine.orchestration import (
    OrchestrationClient,
    BatchConfiguration
)


class DocumentProcessor:
    def __init__(self):
        config = BatchConfiguration(max_concurrent_tasks=10)
        self.client = OrchestrationClient(batch_config=config)

    def process(self, paths):
        return self.client.orchestrate_document_batch(paths)

    def cleanup(self):
        self.client.cleanup()
```

### FastAPI Integration

```python
from fastapi import FastAPI, BackgroundTasks
from doc2md_conversion_engine.orchestration import process_document_async

app = FastAPI()


@app.post("/process")
async def process_document(pdf_path: str):
    """Process document asynchronously."""
    result = await process_document_async(pdf_path)
    return {"markdown_path": result.markdown_path}
```

## Error Handling

All functions raise appropriate exceptions:

```python
from doc2md_conversion_engine.orchestration import convert_single_pdf_to_markdown
from doc2md_conversion_engine.exceptions import (
    ProcessingError,
    ValidationError
)

try:
    result = convert_single_pdf_to_markdown("/data/document.pdf")
except ValidationError as e:
    print(f"Invalid input: {e}")
except ProcessingError as e:
    print(f"Processing failed: {e}")
```

## Best Practices

1. **Use Context Manager**: Always use `with` statement for OrchestrationClient
2. **Configure Concurrency**: Set `max_concurrent_tasks` based on available resources
3. **Enable Pooling**: Use processor pooling for batch processing (reduces overhead)
4. **Handle Failures**: Set `continue_on_error=True` for batch processing
5. **Monitor Metrics**: Track performance metrics to optimize configuration
6. **Async for High Throughput**: Use async API for maximum concurrency
7. **Progress Bars**: Enable for long-running batches, disable for automated systems

## Examples

See the `examples/` directory for complete working examples:

- `example_simple_api.py` - Simple function-based usage
- `example_async_api.py` - Asynchronous processing patterns
- `example_client_usage.py` - Object-oriented client usage

Run examples:

```bash
python doc2md_conversion_engine/orchestration/examples/example_simple_api.py
python doc2md_conversion_engine/orchestration/examples/example_async_api.py
python doc2md_conversion_engine/orchestration/examples/example_client_usage.py
```

## Performance Tuning

### For High Throughput

```python
config = BatchConfiguration(
    max_concurrent_tasks=20,
    max_concurrent_processors=10,
    enable_processor_pooling=True,
    processor_pool_size=10,
    task_timeout_seconds=300.0
)
```

### For Resource-Constrained Environments

```python
config = BatchConfiguration(
    max_concurrent_tasks=2,
    max_concurrent_processors=1,
    enable_processor_pooling=False,
    task_timeout_seconds=None
)
```

### For Fault-Prone Scenarios

```python
config = BatchConfiguration(
    max_retries_per_task=5,
    exponential_backoff=True,
    circuit_breaker_threshold=3,
    continue_on_error=True
)
```

## Testing

The orchestration module includes comprehensive test coverage. Run tests:

```bash
pytest doc2md_conversion_engine/orchestration/tests/
```

## Support

For issues or questions, refer to the main project documentation or contact the development team.




