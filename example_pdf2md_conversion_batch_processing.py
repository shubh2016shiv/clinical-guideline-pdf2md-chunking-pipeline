#!/usr/bin/env python3
"""
Batch document processing test script.

This script demonstrates batch processing of multiple PDFs with async enabled.
Tests the robustness of the pipeline for concurrent document processing.
"""

import logging
import sys
import traceback
import os
from doc2md_conversion_engine.trigger_doc_to_markdown_conversion import start_batch_doc_processing

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

def main():
    print("Starting batch document processing test...")
    print(f"Python version: {sys.version}")
    
    # Let DocumentProcessingConfig handle API key resolution internally
    # It will use: function parameter > environment variable > config default
    print("Using DocumentProcessingConfig for API key resolution")
    print("Processing mode: Asynchronous batch processing")
    print()

    try:
        # Define multiple PDFs to process
        pdf_paths = [
            "clinical_guidelines/Headache.pdf",
            "clinical_guidelines/MASH.pdf"
        ]
        
        print(f"Processing {len(pdf_paths)} documents:")
        for i, path in enumerate(pdf_paths, 1):
            print(f"  {i}. {path}")
        print()
        
        # Process batch of documents with async processing
        # With Gemini enabled, the pipeline will now summarize figures.
        batch_summary = start_batch_doc_processing(
            pdf_file_paths=pdf_paths,
            max_concurrent_tasks=2,  # Process both documents concurrently
            max_retry_attempts=3,
            show_progress_bar=True,
            enable_gemini=True  # Enable Gemini for figure summarization
        )
        
        print("\n" + "=" * 70)
        print("BATCH PROCESSING SUMMARY")
        print("=" * 70)
        print(f"  Batch Request ID: {batch_summary['request_id']}")
        print(f"  Total Documents: {batch_summary['total_documents']}")
        print(f"  Successful: {batch_summary['successful_count']}")
        print(f"  Failed: {batch_summary['failed_count']}")
        print(f"  Success Rate: {batch_summary['success_rate_percentage']}%")
        print(f"  Total Duration: {batch_summary['total_duration_seconds']} seconds")
        print("=" * 70)
        
        # Display individual results
        print("\nINDIVIDUAL DOCUMENT RESULTS:")
        print("-" * 70)
        for i, result in enumerate(batch_summary['individual_results'], 1):
            print(f"\n{i}. {result['pdf_path']}")
            print(f"   Success: {result['success']}")
            
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
        if batch_summary['failed_documents']:
            print("\n" + "=" * 70)
            print("FAILED DOCUMENTS:")
            print("=" * 70)
            for failed_doc in batch_summary['failed_documents']:
                print(f"\n  PDF: {failed_doc['pdf_path']}")
                print(f"  Error: {failed_doc['error_message']}")
        
        print("\n" + "=" * 70)
        
        # Return success if all documents processed successfully
        if batch_summary['failed_count'] == 0:
            print("All documents processed successfully!")
            return 0
        else:
            print(f"Some documents failed ({batch_summary['failed_count']}/{batch_summary['total_documents']})")
            return 1
            
    except ImportError as e:
        print(f"Import Error: {e}")
        print("Module structure or paths might be incorrect")
        traceback.print_exc()
        return 1
    except Exception as e:
        # Extract clean error message for user-facing output
        if hasattr(e, 'message'):
            # For our custom exceptions, use the clean message
            error_message = e.message
        else:
            # For other exceptions, use the string representation
            error_message = str(e)
        
        print(f"Error: {error_message}")
        print("\nFor detailed debugging information, check the logs above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
