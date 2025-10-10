#!/usr/bin/env python3
"""
Orchestration Configuration Package

This package contains configuration classes for controlling orchestration
behavior, including batch processing settings and system-wide parameters.

Exported Classes:
    - BatchConfiguration: Configuration for batch processing operations
    - OrchestrationSettings: System-wide orchestration settings

Usage:
    from doc2md_conversion_engine.orchestration.configuration import (
        BatchConfiguration,
        OrchestrationSettings
    )
    
    batch_config = BatchConfiguration(max_concurrent_tasks=10)
    settings = OrchestrationSettings(enable_metrics_collection=True)
"""

from .batch_configuration import BatchConfiguration
from .orchestration_settings import OrchestrationSettings

__all__ = [
    "BatchConfiguration",
    "OrchestrationSettings",
]




