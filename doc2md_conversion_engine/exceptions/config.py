#!/usr/bin/env python3
"""Configuration-related exceptions for the guideline processor module."""

from .base import GuidelineProcessorError
from typing import Optional, Any


class ConfigurationError(GuidelineProcessorError):
    """Raised when there's a configuration-related error."""
    
    def __init__(
        self, 
        message: str, 
        config_key: Optional[str] = None,
        config_value: Optional[Any] = None,
        error_code: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        Initialize configuration error.
        
        Args:
            message: Error message
            config_key: The configuration key that caused the error
            config_value: The value that caused the error
            error_code: Error code (defaults to "CONFIG_ERROR")
            **kwargs: Additional context
        """
        context = kwargs.pop('context', {})
        if config_key:
            context['config_key'] = config_key
        if config_value is not None:
            context['config_value'] = config_value
            
        super().__init__(
            message=message,
            error_code=error_code or "CONFIG_ERROR",
            context=context,
            **kwargs
        )


class MissingConfigurationError(ConfigurationError):
    """Raised when a required configuration value is missing."""
    
    def __init__(self, config_key: str, **kwargs) -> None:
        """
        Initialize missing configuration error.
        
        Args:
            config_key: The missing configuration key
            **kwargs: Additional context
        """
        super().__init__(
            message=f"Required configuration '{config_key}' is missing",
            config_key=config_key,
            error_code="MISSING_CONFIG",
            **kwargs
        )


class InvalidConfigurationError(ConfigurationError):
    """Raised when a configuration value is invalid."""
    
    def __init__(
        self, 
        config_key: str, 
        config_value: Any, 
        expected_type: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        Initialize invalid configuration error.
        
        Args:
            config_key: The configuration key with invalid value
            config_value: The invalid value
            expected_type: Expected type or format
            **kwargs: Additional context
        """
        message = f"Invalid configuration '{config_key}': {config_value}"
        if expected_type:
            message += f" (expected: {expected_type})"
        
        # Create new context dictionary with expected_type
        context = kwargs.pop('context', {})
        if expected_type:
            context['expected_type'] = expected_type
            
        super().__init__(
            message=message,
            config_key=config_key,
            config_value=config_value,
            error_code="INVALID_CONFIG",
            context=context,
            **kwargs
        )


class APIKeyError(ConfigurationError):
    """Raised when API key is missing or invalid."""
    
    def __init__(
        self,
        api_name: str,
        message: Optional[str] = None,
        **kwargs
    ) -> None:
        """
        Initialize API key error.
        
        Args:
            api_name: Name of the API (e.g., 'Gemini')
            message: Custom error message (optional)
            **kwargs: Additional context
        """
        default_message = f"{api_name} API key is missing or invalid"
        
        # Create new context dictionary with api_name
        context = kwargs.pop('context', {})
        context['api_name'] = api_name
        
        super().__init__(
            message=message or default_message,
            config_key=f"{api_name.lower()}_api_key",
            error_code="API_KEY_ERROR",
            context=context,
            **kwargs
        )