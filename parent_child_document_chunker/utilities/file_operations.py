#!/usr/bin/env python3
"""File utility functions for the document chunker module."""

import os
from pathlib import Path
from typing import Union, Optional
from ..exceptions import FileError, ValidationError


def validate_markdown_file(file_path: Union[str, Path]) -> Path:
    """
    Validate that a file path points to a valid markdown file.
    
    Args:
        file_path: Path to the markdown file
        
    Returns:
        Path object for the validated file
        
    Raises:
        FileError: If the file doesn't exist or isn't readable
        ValidationError: If the file isn't a markdown file
    """
    path = Path(file_path)
    
    if not path.exists():
        raise FileError(
            f"Markdown file not found: {path}",
            file_path=str(path),
            operation="validation"
        )
    
    if not path.is_file():
        raise FileError(
            f"Path is not a file: {path}",
            file_path=str(path),
            operation="validation"
        )
    
    if not os.access(path, os.R_OK):
        raise FileError(
            f"File is not readable: {path}",
            file_path=str(path),
            operation="validation"
        )
    
    # Check file extension
    if path.suffix.lower() not in ['.md', '.markdown']:
        raise ValidationError(
            f"File is not a markdown file: {path}",
            field="file_extension",
            value=path.suffix
        )
    
    return path


def ensure_directory(directory_path: Union[str, Path], create: bool = True) -> Path:
    """
    Ensure a directory exists, optionally creating it.
    
    Args:
        directory_path: Path to the directory
        create: Whether to create the directory if it doesn't exist
        
    Returns:
        Path object for the directory
        
    Raises:
        FileError: If directory creation fails or path is invalid
    """
    path = Path(directory_path)
    
    if path.exists() and not path.is_dir():
        raise FileError(
            f"Path exists but is not a directory: {path}",
            file_path=str(path),
            operation="directory_validation"
        )
    
    if not path.exists() and create:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise FileError(
                f"Failed to create directory: {path}",
                file_path=str(path),
                operation="directory_creation",
                **{"error": str(e)}
            )
    
    return path


def get_output_path(
    source_path: Union[str, Path],
    output_dir: Union[str, Path],
    filename: Optional[str] = None,
    extension: str = ".json"
) -> Path:
    """
    Generate an output file path for chunked documents.
    
    Args:
        source_path: Path to the source markdown file
        output_dir: Output directory
        filename: Custom filename (without extension)
        extension: File extension
        
    Returns:
        Path object for the output file
    """
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    
    if filename:
        output_filename = f"{filename}{extension}"
    else:
        # Use source filename with chunked suffix
        output_filename = f"{source_path.stem}_chunked{extension}"
    
    return output_dir / output_filename
