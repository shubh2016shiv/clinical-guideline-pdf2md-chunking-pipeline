#!/usr/bin/env python3
"""
Example: Using the OrchestrationClient

This example demonstrates how to use the OrchestrationClient class
directly for more control over orchestration behavior. This is the
object-oriented approach suitable for applications that need fine-grained
control over configuration and lifecycle.

Use the client approach when you need:
- Custom configuration for different operations
- Direct access to metrics and status
- Explicit resource management
- Integration with existing OOP codebases
"""

from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from doc2md_conversion_engine.orchestration import (
    OrchestrationClient,
    BatchConfiguration,
    OrchestrationSettings
)


def example_basic_client():
    """Example: Basic client usage with context manager."""
    print("=" * 70)
    print("Example 1: Basic Client Usage")
    print("=" * 70)
    
    # Use client with context manager (auto cleanup)
    with OrchestrationClient() as client:
        # Process single document
        result = client.orchestrate_single_document(
            pdf_path="clinical_guidelines/MASH.pdf",
            output_path="output/client_example"
        )
        print(f"✓ Document processed: {result.markdown_path}")
    
    print("Client automatically cleaned up (context manager)")


def example_custom_configuration():
    """Example: Client with custom configuration."""
    print("\n" + "=" * 70)
    print("Example 2: Custom Configuration")
    print("=" * 70)
    
    # Create custom batch configuration
    batch_config = BatchConfiguration(
        max_concurrent_tasks=10,
        max_concurrent_processors=5,
        max_retries_per_task=5,
        retry_delay_seconds=1.0,
        exponential_backoff=True,
        enable_processor_pooling=True,
        processor_pool_size=5,
        task_timeout_seconds=300.0,
        enable_progress_reporting=True,
        log_level="INFO"
    )
    
    # Create custom orchestration settings
    settings = OrchestrationSettings(
        enable_metrics_collection=True,
        enable_detailed_logging=False,
        cleanup_on_shutdown=True
    )
    
    # Create client with custom config
    client = OrchestrationClient(
        batch_config=batch_config,
        settings=settings
    )
    
    try:
        # Process documents
        pdf_files = [
            "clinical_guidelines/MASH.pdf",
            "clinical_guidelines/Headache.pdf"
        ]
        
        results = client.orchestrate_document_batch(
            pdf_paths=pdf_files,
            use_async=True
        )
        
        # Show results
        successful = sum(1 for t in results if t.result)
        print(f"Processed {len(results)} documents: {successful} successful")
        
    finally:
        # Manual cleanup
        client.cleanup()


def example_metrics_tracking():
    """Example: Using metrics tracking."""
    print("\n" + "=" * 70)
    print("Example 3: Metrics Tracking")
    print("=" * 70)
    
    # Create client with metrics enabled
    config = BatchConfiguration(enable_progress_reporting=True)
    settings = OrchestrationSettings(enable_metrics_collection=True)
    
    with OrchestrationClient(batch_config=config, settings=settings) as client:
        # Process some documents
        pdf_files = [
            "clinical_guidelines/MASH.pdf",
            "clinical_guidelines/Headache.pdf"
        ]
        
        client.orchestrate_document_batch(pdf_files)
        
        # Get metrics
        metrics = client.get_orchestration_metrics()
        
        # Display metrics
        print("\nPerformance Metrics:")
        print(f"  Total Tasks: {metrics.get('total_tasks', 0)}")
        print(f"  Completed: {metrics.get('completed_tasks', 0)}")
        print(f"  Failed: {metrics.get('failed_tasks', 0)}")
        print(f"  Success Rate: {metrics.get('success_rate', 0):.1f}%")
        print(f"  Avg Processing Time: {metrics.get('average_processing_time', 0):.2f}s")
        print(f"  Throughput: {metrics.get('throughput_tasks_per_second', 0):.2f} tasks/s")
        
        # Circuit breaker status
        cb_status = metrics.get('circuit_breaker_status', {})
        print(f"\nCircuit Breaker:")
        print(f"  Open: {cb_status.get('is_open', False)}")
        print(f"  Failures: {cb_status.get('failures', 0)}/{cb_status.get('threshold', 0)}")


def example_directory_processing():
    """Example: Processing entire directory."""
    print("\n" + "=" * 70)
    print("Example 4: Directory Processing")
    print("=" * 70)
    
    config = BatchConfiguration(
        max_concurrent_tasks=5,
        enable_progress_reporting=True
    )
    
    with OrchestrationClient(batch_config=config) as client:
        # Process entire directory
        results = client.orchestrate_directory_processing(
            directory_path="clinical_guidelines",
            file_pattern="*.pdf",
            output_path="output/directory_client"
        )
        
        # Analyze results
        print(f"\nDirectory Processing Results:")
        for task in results:
            name = Path(task.pdf_path).name
            if task.result:
                print(f"  ✓ {name} - {task.duration:.2f}s - {task.attempts} attempts")
            else:
                print(f"  ✗ {name} - {task.error}")


def example_error_handling():
    """Example: Error handling and retries."""
    print("\n" + "=" * 70)
    print("Example 5: Error Handling and Retries")
    print("=" * 70)
    
    # Configure with aggressive retries
    config = BatchConfiguration(
        max_retries_per_task=5,
        retry_delay_seconds=1.0,
        exponential_backoff=True,
        continue_on_error=True,  # Continue even if some fail
        circuit_breaker_threshold=10  # High threshold
    )
    
    with OrchestrationClient(batch_config=config) as client:
        # Try processing with some potentially problematic files
        pdf_files = [
            "clinical_guidelines/MASH.pdf",
            "nonexistent_file.pdf",  # This will fail
            "clinical_guidelines/Headache.pdf"
        ]
        
        results = client.orchestrate_document_batch(pdf_files)
        
        # Categorize results
        successful = [t for t in results if t.result]
        failed = [t for t in results if not t.result]
        retried = [t for t in results if t.attempts > 1]
        
        print(f"\nResults:")
        print(f"  Total: {len(results)}")
        print(f"  Successful: {len(successful)}")
        print(f"  Failed: {len(failed)}")
        print(f"  Required Retry: {len(retried)}")
        
        # Show retry details
        if retried:
            print(f"\nRetry Details:")
            for task in retried:
                name = Path(task.pdf_path).name
                status = "✓" if task.result else "✗"
                print(f"  {status} {name} - {task.attempts} attempts")


def main():
    """Run all client examples."""
    print("\n" + "=" * 70)
    print("ORCHESTRATION CLIENT EXAMPLES")
    print("=" * 70)
    
    # Run examples
    example_basic_client()
    example_custom_configuration()
    example_metrics_tracking()
    example_directory_processing()
    example_error_handling()
    
    print("\n" + "=" * 70)
    print("All client examples completed!")
    print("=" * 70)


if __name__ == "__main__":
    main()




