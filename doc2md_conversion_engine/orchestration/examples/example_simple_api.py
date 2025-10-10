#!/usr/bin/env python3
"""
Example: Using the Simple API

This example demonstrates how to use the simple function-based API
for document processing orchestration. This is the easiest way to
integrate document processing into your application.

The simple API handles all orchestration complexity internally, providing
clean function calls for common operations.
"""

from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from doc2md_conversion_engine.orchestration import (
    convert_single_pdf_to_markdown,
    convert_pdf_batch_to_markdown,
    convert_directory_pdfs_to_markdown,
    get_default_conversion_settings
)


def example_single_document():
    """Example: Process a single document."""
    print("=" * 70)
    print("Example 1: Processing Single Document")
    print("=" * 70)
    
    # Process single document with defaults
    try:
        result = convert_single_pdf_to_markdown(
            pdf_path="clinical_guidelines/MASH.pdf",
            output_path="output/example",
            max_retries=3
        )
        print(f"✓ Successfully processed document")
        print(f"  Markdown: {result.markdown_path}")
        print(f"  Figures: {len(result.figures)}")
    except Exception as e:
        print(f"✗ Processing failed: {e}")


def example_batch_documents():
    """Example: Process multiple documents as a batch."""
    print("\n" + "=" * 70)
    print("Example 2: Batch Processing Multiple Documents")
    print("=" * 70)
    
    # List of PDF files to process
    pdf_files = [
        "clinical_guidelines/MASH.pdf",
        "clinical_guidelines/Headache.pdf"
    ]
    
    # Process batch with custom concurrency
    results = convert_pdf_batch_to_markdown(
        pdf_paths=pdf_files,
        output_path="output/batch",
        max_concurrent=2,
        max_retries=3,
        show_progress=True
    )
    
    # Print summary
    print(f"\nProcessed {len(results)} documents:")
    for result in results:
        status = "✓" if result['success'] else "✗"
        name = Path(result['pdf_path']).name
        if result['success']:
            print(f"  {status} {name} - {result['duration']:.2f}s")
        else:
            print(f"  {status} {name} - Error: {result['error']}")
    
    # Calculate success rate
    successful = sum(1 for r in results if r['success'])
    success_rate = (successful / len(results)) * 100
    print(f"\nSuccess Rate: {success_rate:.1f}% ({successful}/{len(results)})")


def example_directory_processing():
    """Example: Process all PDFs in a directory."""
    print("\n" + "=" * 70)
    print("Example 3: Processing Entire Directory")
    print("=" * 70)
    
    # Process all PDFs in directory
    summary = convert_directory_pdfs_to_markdown(
        directory_path="clinical_guidelines",
        file_pattern="*.pdf",
        output_path="output/directory",
        max_concurrent=3,
        show_progress=True
    )
    
    # Print comprehensive summary
    print(f"\nDirectory Processing Summary:")
    print(f"  Total Files: {summary['total_files']}")
    print(f"  Successful: {summary['successful']}")
    print(f"  Failed: {summary['failed']}")
    print(f"  Success Rate: {summary['success_rate']:.1f}%")
    
    # Show failed files if any
    if summary['failed_files']:
        print(f"\nFailed Files:")
        for failure in summary['failed_files']:
            print(f"  ✗ {Path(failure['path']).name}: {failure['error']}")


def example_custom_configuration():
    """Example: Using custom configuration."""
    print("\n" + "=" * 70)
    print("Example 4: Custom Configuration")
    print("=" * 70)
    
    # Get default configuration
    config = get_default_conversion_settings()
    print(f"Default Configuration:")
    for key, value in config.items():
        print(f"  {key}: {value}")
    
    # Customize configuration
    config['max_concurrent'] = 10
    config['max_retries'] = 5
    config['enable_processor_pooling'] = True
    config['processor_pool_size'] = 5
    
    print(f"\nProcessing with custom configuration...")
    # Use custom config with batch processing
    results = convert_pdf_batch_to_markdown(
        pdf_paths=["clinical_guidelines/MASH.pdf"],
        **config
    )
    
    print(f"Processed {len(results)} document(s) with custom config")


def main():
    """Run all examples."""
    print("\n" + "=" * 70)
    print("SIMPLE API EXAMPLES")
    print("=" * 70)
    
    # Run examples
    example_single_document()
    example_batch_documents()
    example_directory_processing()
    example_custom_configuration()
    
    print("\n" + "=" * 70)
    print("All examples completed!")
    print("=" * 70)


if __name__ == "__main__":
    main()




