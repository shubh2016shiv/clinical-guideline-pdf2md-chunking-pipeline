#!/usr/bin/env python3
"""
Simple test script to verify document processing functionality.
"""

import logging
import sys
import traceback
import os
from doc2md_conversion_engine.models.config import DocumentProcessingConfig
from doc2md_conversion_engine.trigger_doc_to_markdown_conversion import start_single_doc_processing

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
    print("Starting document processing test...")
    print(f"Python version: {sys.version}")
    
    # Let DocumentProcessingConfig handle API key resolution internally
    # It will use: function parameter > environment variable > config default
    print("Using DocumentProcessingConfig for API key resolution")

    try:
        pdf_path = "clinical_guidelines/MASH.pdf"
        print(f"Processing document: {pdf_path}")
        
        # Process a single document with Gemini enabled
        # Let the config handle API key resolution internally
        result = start_single_doc_processing(
            pdf_file_path=pdf_path,
            enable_gemini=True
        )
        
        print("\n" + "=" * 50)
        print("Processing Result:")
        print(f"  Success: {result['success']}")
        print(f"  Request ID: {result['request_id']}")
        print(f"  PDF Path: {result['pdf_path']}")
        
        if result['success']:
            print(f"  Markdown Path: {result['markdown_path']}")
            print(f"  Figures Extracted: {result['figures_extracted']}")
            print(f"  Tables Extracted: {result['tables_extracted']}")
        else:
            print(f"  Error: {result['error_message']}")
        
        print(f"  Processing Duration: {result['processing_duration_seconds']} seconds")
        print("=" * 50)
        
        return 0
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