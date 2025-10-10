#!/usr/bin/env python3
"""File utility functions for the guideline processor module."""

import os
import mimetypes
from pathlib import Path
from typing import Optional, Union

from ..exceptions import FileValidationError


def validate_pdf_file(file_path: Union[str, Path]) -> Path:
    """
    Validate that a file is a valid PDF.
    
    Args:
        file_path: Path to the file to validate
        
    Returns:
        Path object for the validated file
        
    Raises:
        FileValidationError: If the file is not a valid PDF
    """
    file_path = Path(file_path)
    
    # Check if file exists
    if not file_path.exists():
        raise FileValidationError(
            str(file_path),
            "File does not exist"
        )
    
    # Check if it's a file (not directory)
    if not file_path.is_file():
        raise FileValidationError(
            str(file_path),
            "Path is not a file"
        )
    
    # Check file extension
    if file_path.suffix.lower() != '.pdf':
        raise FileValidationError(
            str(file_path),
            "File is not a PDF",
            expected_format="PDF"
        )
    
    # Check file size (must be > 0 bytes)
    if file_path.stat().st_size == 0:
        raise FileValidationError(
            str(file_path),
            "File is empty"
        )
    
    # Check MIME type if possible
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type and mime_type != 'application/pdf':
        raise FileValidationError(
            str(file_path),
            f"File has incorrect MIME type: {mime_type}",
            expected_format="application/pdf"
        )
    
    return file_path


def ensure_directory(directory_path: Union[str, Path], create: bool = True) -> Path:
    """
    Ensure a directory exists, optionally creating it.
    
    Args:
        directory_path: Path to the directory
        create: Whether to create the directory if it doesn't exist
        
    Returns:
        Path object for the directory
        
    Raises:
        OSError: If directory creation fails
    """
    directory_path = Path(directory_path)
    
    if create and not directory_path.exists():
        directory_path.mkdir(parents=True, exist_ok=True)
    
    return directory_path


def get_safe_filename(filename: str, max_length: int = 255) -> str:
    """
    Convert a filename to a safe version for filesystem use.
    
    Args:
        filename: Original filename
        max_length: Maximum length for the filename
        
    Returns:
        Safe filename
    """
    # Remove or replace problematic characters
    safe_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    
    # Convert to safe characters
    safe_name = ""
    for char in filename:
        if char in safe_chars:
            safe_name += char
        elif char.isspace():
            safe_name += "_"
        else:
            safe_name += "_"
    
    # Remove multiple consecutive underscores
    while "__" in safe_name:
        safe_name = safe_name.replace("__", "_")
    
    # Remove leading/trailing underscores and dots
    safe_name = safe_name.strip("_.")
    
    # Ensure it's not empty
    if not safe_name:
        safe_name = "file"
    
    # Truncate if too long
    if len(safe_name) > max_length:
        # Preserve extension if present
        if "." in safe_name:
            name_part, ext_part = safe_name.rsplit(".", 1)
            max_name_length = max_length - len(ext_part) - 1
            safe_name = name_part[:max_name_length] + "." + ext_part
        else:
            safe_name = safe_name[:max_length]
    
    return safe_name


def normalize_path(path: Union[str, Path]) -> Path:
    """
    Normalize a file path.
    
    Args:
        path: Path to normalize
        
    Returns:
        Normalized Path object
    """
    return Path(path).resolve()


def get_file_size_mb(file_path: Union[str, Path]) -> float:
    """
    Get file size in megabytes.
    
    Args:
        file_path: Path to the file
        
    Returns:
        File size in MB
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return 0.0
    
    size_bytes = file_path.stat().st_size
    return size_bytes / (1024 * 1024)


def is_readable_file(file_path: Union[str, Path]) -> bool:
    """
    Check if a file is readable.
    
    Args:
        file_path: Path to the file
        
    Returns:
        True if file is readable, False otherwise
    """
    file_path = Path(file_path)
    return file_path.exists() and os.access(file_path, os.R_OK)


def is_writable_directory(directory_path: Union[str, Path]) -> bool:
    """
    Check if a directory is writable.
    
    Args:
        directory_path: Path to the directory
        
    Returns:
        True if directory is writable, False otherwise
    """
    directory_path = Path(directory_path)
    return directory_path.exists() and os.access(directory_path, os.W_OK)
