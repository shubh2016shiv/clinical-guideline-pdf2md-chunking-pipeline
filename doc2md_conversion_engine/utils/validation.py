#!/usr/bin/env python3
"""Validation utility functions for the guideline processor module."""

from typing import Any, Dict, List, Optional, Union
from pathlib import Path
import os

from ..exceptions import ValidationError, ConfigurationError
from ..models.config import DocumentProcessingConfig


def validate_config(config: DocumentProcessingConfig) -> None:
    """
    Validate configuration object.
    
    Args:
        config: Configuration to validate
        
    Raises:
        ConfigurationError: If configuration is invalid
    """
    if not isinstance(config, DocumentProcessingConfig):
        raise ConfigurationError(
            "Configuration must be a GuidelineConfig instance",
            config_key="config",
            config_value=type(config).__name__
        )
    
    # Validate output directory
    if not config.output_dir:
        raise ConfigurationError(
            "Output directory cannot be empty",
            config_key="output_dir"
        )
    
    # Validate image format
    if config.image_format not in ["PNG", "JPEG", "JPG"]:
        raise ConfigurationError(
            f"Invalid image format: {config.image_format}",
            config_key="image_format",
            config_value=config.image_format,
            expected_type="PNG, JPEG, or JPG"
        )
    
    # Validate numeric ranges
    if config.image_dpi <= 0:
        raise ConfigurationError(
            f"Image DPI must be positive: {config.image_dpi}",
            config_key="image_dpi",
            config_value=config.image_dpi
        )
    
    if config.max_image_workers <= 0:
        raise ConfigurationError(
            f"Max image workers must be positive: {config.max_image_workers}",
            config_key="max_image_workers",
            config_value=config.max_image_workers
        )
    
    if not 0.0 <= config.gemini_temperature <= 1.0:
        raise ConfigurationError(
            f"Gemini temperature must be between 0.0 and 1.0: {config.gemini_temperature}",
            config_key="gemini_temperature",
            config_value=config.gemini_temperature
        )
    
    # Validate Gemini configuration
    if config.enable_gemini and not config.gemini_api_key:
        raise ConfigurationError(
            "Gemini API key is required when Gemini is enabled",
            config_key="gemini_api_key"
        )


def validate_file_path(file_path: Union[str, Path], 
                      must_exist: bool = True,
                      must_be_file: bool = True,
                      must_be_readable: bool = True) -> Path:
    """
    Validate file path.
    
    Args:
        file_path: Path to validate
        must_exist: Whether file must exist
        must_be_file: Whether path must be a file (not directory)
        must_be_readable: Whether file must be readable
        
    Returns:
        Validated Path object
        
    Raises:
        ValidationError: If validation fails
    """
    file_path = Path(file_path)
    
    if must_exist and not file_path.exists():
        raise ValidationError(
            f"File does not exist: {file_path}",
            field="file_path",
            value=str(file_path)
        )
    
    if must_be_file and file_path.exists() and not file_path.is_file():
        raise ValidationError(
            f"Path is not a file: {file_path}",
            field="file_path",
            value=str(file_path)
        )
    
    if must_be_readable and file_path.exists() and not file_path.is_file():
        raise ValidationError(
            f"File is not readable: {file_path}",
            field="file_path",
            value=str(file_path)
        )
    
    return file_path


def validate_image_format(format_str: str) -> str:
    """
    Validate image format string.
    
    Args:
        format_str: Format string to validate
        
    Returns:
        Normalized format string
        
    Raises:
        ValidationError: If format is invalid
    """
    if not format_str:
        raise ValidationError(
            "Image format cannot be empty",
            field="image_format"
        )
    
    format_str = format_str.upper()
    
    if format_str not in ["PNG", "JPEG", "JPG"]:
        raise ValidationError(
            f"Invalid image format: {format_str}",
            field="image_format",
            value=format_str,
            expected_type="PNG, JPEG, or JPG"
        )
    
    return format_str


def validate_output_directory(directory_path: Union[str, Path], 
                            create_if_missing: bool = True) -> Path:
    """
    Validate output directory.
    
    Args:
        directory_path: Directory path to validate
        create_if_missing: Whether to create directory if it doesn't exist
        
    Returns:
        Validated Path object
        
    Raises:
        ValidationError: If validation fails
    """
    directory_path = Path(directory_path)
    
    if directory_path.exists():
        if not directory_path.is_dir():
            raise ValidationError(
                f"Path exists but is not a directory: {directory_path}",
                field="output_directory",
                value=str(directory_path)
            )
        
        if not os.access(directory_path, os.W_OK):
            raise ValidationError(
                f"Directory is not writable: {directory_path}",
                field="output_directory",
                value=str(directory_path)
            )
    else:
        if create_if_missing:
            try:
                directory_path.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise ValidationError(
                    f"Failed to create directory: {directory_path}",
                    field="output_directory",
                    value=str(directory_path)
                ) from e
        else:
            raise ValidationError(
                f"Directory does not exist: {directory_path}",
                field="output_directory",
                value=str(directory_path)
            )
    
    return directory_path


def validate_positive_integer(value: Any, field_name: str) -> int:
    """
    Validate that a value is a positive integer.
    
    Args:
        value: Value to validate
        field_name: Name of the field for error messages
        
    Returns:
        Validated integer value
        
    Raises:
        ValidationError: If validation fails
    """
    try:
        int_value = int(value)
    except (ValueError, TypeError):
        raise ValidationError(
            f"Field '{field_name}' must be an integer",
            field=field_name,
            value=value
        )
    
    if int_value <= 0:
        raise ValidationError(
            f"Field '{field_name}' must be positive",
            field=field_name,
            value=int_value
        )
    
    return int_value


def validate_float_range(value: Any, field_name: str, 
                        min_value: float, max_value: float) -> float:
    """
    Validate that a value is a float within a specified range.
    
    Args:
        value: Value to validate
        field_name: Name of the field for error messages
        min_value: Minimum allowed value
        max_value: Maximum allowed value
        
    Returns:
        Validated float value
        
    Raises:
        ValidationError: If validation fails
    """
    try:
        float_value = float(value)
    except (ValueError, TypeError):
        raise ValidationError(
            f"Field '{field_name}' must be a number",
            field=field_name,
            value=value
        )
    
    if not min_value <= float_value <= max_value:
        raise ValidationError(
            f"Field '{field_name}' must be between {min_value} and {max_value}",
            field=field_name,
            value=float_value
        )
    
    return float_value


def validate_string_not_empty(value: Any, field_name: str) -> str:
    """
    Validate that a value is a non-empty string.
    
    Args:
        value: Value to validate
        field_name: Name of the field for error messages
        
    Returns:
        Validated string value
        
    Raises:
        ValidationError: If validation fails
    """
    if not isinstance(value, str):
        raise ValidationError(
            f"Field '{field_name}' must be a string",
            field=field_name,
            value=value
        )
    
    if not value.strip():
        raise ValidationError(
            f"Field '{field_name}' cannot be empty",
            field=field_name,
            value=value
        )
    
    return value.strip()
