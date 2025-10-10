#!/usr/bin/env python3
"""
Example: Using the Async API

This example demonstrates how to use the asynchronous API for
document processing orchestration. Use this API when integrating
with async frameworks or when you need non-blocking operation.

The async API provides maximum concurrency and is ideal for
high-throughput scenarios and async web frameworks.
"""

import asyncio
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from doc2md_conversion_engine.orchestration import (
    process_document_async,
    process_documents_async,
    process_directory_async,
    process_concurrent_batches
)


async def example_single_document_async():
    """Example: Process a single document asynchronously."""
    print("=" * 70)
    print("Example 1: Async Single Document Processing")
    print("=" * 70)
    
    try:
        result = await process_document_async(
            pdf_path="clinical_guidelines/MASH.pdf",
            output_path="output/async_example",
            max_retries=3
        )
        print(f"✓ Successfully processed document")
        print(f"  Markdown: {result.markdown_path}")
        print(f"  Figures: {len(result.figures)}")
    except Exception as e:
        print(f"✗ Processing failed: {e}")


async def example_batch_async():
    """Example: Process batch asynchronously."""
    print("\n" + "=" * 70)
    print("Example 2: Async Batch Processing")
    print("=" * 70)
    
    pdf_files = [
        "clinical_guidelines/MASH.pdf",
        "clinical_guidelines/Headache.pdf"
    ]
    
    # Process asynchronously with high concurrency
    results = await process_documents_async(
        pdf_paths=pdf_files,
        max_concurrent=10,  # Higher concurrency for async
        max_retries=3
    )
    
    # Print results
    print(f"\nProcessed {len(results)} documents asynchronously:")
    for result in results:
        status = "✓" if result['success'] else "✗"
        name = Path(result['pdf_path']).name
        if result['success']:
            print(f"  {status} {name} - {result['duration']:.2f}s")
        else:
            print(f"  {status} {name} - Error: {result['error']}")


async def example_directory_async():
    """Example: Process directory asynchronously."""
    print("\n" + "=" * 70)
    print("Example 3: Async Directory Processing")
    print("=" * 70)
    
    summary = await process_directory_async(
        directory_path="clinical_guidelines",
        max_concurrent=5
    )
    
    print(f"\nAsync Directory Processing Summary:")
    print(f"  Total Files: {summary['total_files']}")
    print(f"  Successful: {summary['successful']}")
    print(f"  Failed: {summary['failed']}")
    print(f"  Success Rate: {summary['success_rate']:.1f}%")


async def example_concurrent_batches():
    """Example: Process multiple batches concurrently."""
    print("\n" + "=" * 70)
    print("Example 4: Concurrent Batch Processing")
    print("=" * 70)
    
    # Define multiple batches
    batch1 = ["clinical_guidelines/MASH.pdf"]
    batch2 = ["clinical_guidelines/Headache.pdf"]
    
    print(f"Processing {len([batch1, batch2])} batches concurrently...")
    
    # Process all batches concurrently
    results = await process_concurrent_batches(
        batch_paths=[batch1, batch2],
        max_concurrent_per_batch=3
    )
    
    # Print results for each batch
    for i, batch_results in enumerate(results, 1):
        successful = sum(1 for r in batch_results if r['success'])
        print(f"  Batch {i}: {successful}/{len(batch_results)} successful")


async def example_parallel_operations():
    """Example: Multiple async operations in parallel."""
    print("\n" + "=" * 70)
    print("Example 5: Parallel Async Operations")
    print("=" * 70)
    
    print("Starting multiple async operations in parallel...")
    
    # Create multiple async tasks
    task1 = process_document_async("clinical_guidelines/MASH.pdf")
    task2 = process_document_async("clinical_guidelines/Headache.pdf")
    
    # Run them concurrently and wait for all
    results = await asyncio.gather(task1, task2, return_exceptions=True)
    
    # Check results
    successful = sum(1 for r in results if not isinstance(r, Exception))
    print(f"Completed {len(results)} operations: {successful} successful")


async def main():
    """Run all async examples."""
    print("\n" + "=" * 70)
    print("ASYNC API EXAMPLES")
    print("=" * 70)
    
    # Run all examples
    await example_single_document_async()
    await example_batch_async()
    await example_directory_async()
    await example_concurrent_batches()
    await example_parallel_operations()
    
    print("\n" + "=" * 70)
    print("All async examples completed!")
    print("=" * 70)


if __name__ == "__main__":
    # Run async main
    asyncio.run(main())




