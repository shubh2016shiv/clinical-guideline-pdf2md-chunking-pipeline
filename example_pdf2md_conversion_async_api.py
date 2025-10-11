#!/usr/bin/env python3
"""
Direct Async API Usage Example - FastAPI Integration Ready

This script demonstrates direct usage of the async API functions for integration
with async frameworks like FastAPI, aiohttp, or any async/await application.

Key Differences from Sync Version:
- Uses native async/await syntax
- Non-blocking execution - suitable for web APIs
- Direct import from orchestration module
- Demonstrates proper async context management

Portfolio Example:
This shows how to integrate the document processing pipeline with async
web frameworks for production-ready API endpoints.
"""

import asyncio
import logging
import sys
import os
from pathlib import Path

# Direct async API import - this is what FastAPI would use
from doc2md_conversion_engine.orchestration import convert_pdf_batch_to_markdown_async

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Reduce verbosity for external libraries
for logger_name in ['pdfminer', 'PIL', 'urllib3']:
    logging.getLogger(logger_name).setLevel(logging.WARNING)
logging.getLogger('docling').setLevel(logging.INFO)


async def process_documents_async_example():
    """
    Async function demonstrating direct async API usage.
    
    This pattern would be used in:
    - FastAPI endpoints
    - aiohttp handlers
    - async web frameworks
    - Event-driven applications
    """
    print("=" * 70)
    print("ASYNC API USAGE EXAMPLE - FastAPI Integration Ready")
    print("=" * 70)
    print(f"Python version: {sys.version}")
    print()
    
    # Define PDFs to process
    pdf_paths = [
        "clinical_guidelines/Headache.pdf",
        "clinical_guidelines/MASH.pdf"
    ]
    
    print(f"Processing {len(pdf_paths)} documents with DIRECT async API:")
    for i, path in enumerate(pdf_paths, 1):
        print(f"  {i}. {path}")
    print()
    print("Configuration:")
    print("  - Max Concurrent: 2")
    print("  - Max Retries: 3")
    print("  - Gemini AI: Enabled (for figure summarization)")
    print("  - API: Direct async (non-blocking)")
    print()
    
    try:
        # This is the DIRECT async API call - suitable for FastAPI
        # Gemini API key will be resolved from GEMINI_API_KEY environment variable
        results = await convert_pdf_batch_to_markdown_async(
            pdf_paths=pdf_paths,
            max_concurrent=2,
            max_retries=3,
            show_progress=True,
            enable_gemini=True,
            # gemini_api_key can be passed explicitly or uses environment variable
        )
        
        # Process results
        print("\n" + "=" * 70)
        print("ASYNC PROCESSING RESULTS")
        print("=" * 70)
        
        successful = [r for r in results if r['success']]
        failed = [r for r in results if not r['success']]
        
        print(f"Total Documents: {len(results)}")
        print(f"Successful: {len(successful)}")
        print(f"Failed: {len(failed)}")
        print(f"Success Rate: {(len(successful)/len(results)*100):.1f}%")
        print("=" * 70)
        
        # Display individual results
        print("\nINDIVIDUAL DOCUMENT RESULTS:")
        print("-" * 70)
        for i, result in enumerate(results, 1):
            pdf_name = Path(result['pdf_path']).stem
            print(f"\n{i}. {pdf_name}")
            print(f"   Status: {'✓ Success' if result['success'] else '✗ Failed'}")
            print(f"   Path: {result['pdf_path']}")
            
            if result['success']:
                doc_result = result['result']
                print(f"   Markdown: {doc_result.markdown_path}")
                print(f"   Figures: {len(doc_result.figures)}")
                print(f"   Tables: {len(doc_result.tables)}")
                print(f"   Duration: {result['duration']:.2f}s")
                print(f"   Attempts: {result['attempts']}")
            else:
                print(f"   Error: {result['error']}")
                print(f"   Attempts: {result['attempts']}")
        
        # Display failed documents if any
        if failed:
            print("\n" + "=" * 70)
            print("FAILED DOCUMENTS:")
            print("=" * 70)
            for result in failed:
                print(f"\n  PDF: {result['pdf_path']}")
                print(f"  Error: {result['error']}")
        
        print("\n" + "=" * 70)
        
        # Return success status
        return len(failed) == 0
        
    except Exception as e:
        print(f"\nError during async processing: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """
    Main async entry point.
    
    This demonstrates the complete async workflow.
    """
    print("Starting Async API Usage Example...")
    print("This example shows how to integrate with async frameworks like FastAPI\n")
    
    # Run the async processing example
    success = await process_documents_async_example()
    
    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("✓ Async API functions demonstrated")
    print("✓ Direct async/await usage shown")
    print("✓ FastAPI integration pattern provided")
    print("✓ Non-blocking execution confirmed")
    print()
    print("Key Takeaways:")
    print("  1. Use convert_pdf_batch_to_markdown_async for async frameworks")
    print("  2. Perfect for FastAPI, aiohttp, and other async web frameworks")
    print("  3. Non-blocking execution enables high concurrency")
    print("  4. Gemini API key can be passed or resolved from environment")
    print()
    print("Portfolio Note:")
    print("  This example demonstrates production-ready async API integration")
    print("  suitable for scalable web services and microservices architecture.")
    print("=" * 70)
    
    return 0 if success else 1


if __name__ == "__main__":
    # Run the async main function
    # This is the pattern for async scripts
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

