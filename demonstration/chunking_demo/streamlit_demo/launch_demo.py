#!/usr/bin/env python3
"""Launcher script for the Streamlit Parent-Child Chunker Visualizer."""

import subprocess
import sys
import os
from pathlib import Path

# Add project root to sys.path to allow importing 'parent_child_document_chunker'
# This script is in demonstration/chunking_demo/streamlit_demo, so root is 4 levels up.
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

def check_dependencies():
    """Check if required dependencies are installed."""
    try:
        import streamlit
        import pandas
        print(" [INFO] Streamlit and pandas are available")
    except ImportError as e:
        print(f"[ERROR] Missing dependency: {e}")
        print("Please install required dependencies:")
        print("pip install -r streamlit_requirements.txt")
        return False
    
    try:
        from parent_child_document_chunker import DocumentChunker
        print(" [INFO] Document chunker module is available")
    except ImportError as e:
        print(f"[ERROR] Document chunker not available: {e}")
        print("Please ensure the 'parent_child_document_chunker' directory is at the project root.")
        return False
    
    return True

def launch_app():
    """Launch the Streamlit app."""
    app_path = Path(__file__).parent / "parent_child_chunking_ui.py"
    
    if not app_path.exists():
        print(f"[ERROR] Streamlit app not found: {app_path}")
        return False
    
    print("Launching Parent-Child Chunker Visualizer...")
    print("The app will open in your default web browser")
    print("If it doesn't open automatically, go to: http://localhost:8501")
    print("\n Tips:")
    print("   - Upload your output.md file using the sidebar")
    print("   - Configure chunking parameters as needed")
    print("   - Click 'Process Document' to start chunking")
    print("   - Explore parent chunks and their children")
    print("\n  Press Ctrl+C to stop the app")
    
    try:
        # Launch Streamlit app
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", str(app_path),
            "--server.port", "8501",
            "--server.address", "localhost"
        ])
    except KeyboardInterrupt:
        print("\nApp stopped by user")
    except Exception as e:
        print(f"Error launching app: {e}")
        return False
    
    return True

def main():
    """Main launcher function."""
    print("Structure-Aware Parent-Child Chunking Visualizer")
    print("=" * 50)
    
    # Check dependencies
    if not check_dependencies():
        print("\n [ERROR] Cannot launch app due to missing dependencies")
        return 1
    
    print("\n [INFO] All dependencies are available!")
    
    # Launch the app
    if launch_app():
        print("\n [INFO] App launched successfully!")
        return 0
    else:
        print("\n [ERROR] Failed to launch app")
        return 1

if __name__ == "__main__":
    sys.exit(main())
