#!/usr/bin/env python3
"""
Data models for hardware acceleration and device configuration.

This module defines the data structures used for representing
hardware accelerators, device information, and configuration settings.
"""

from enum import Enum
from typing import Optional, Dict, Tuple
from dataclasses import dataclass


class AcceleratorType(Enum):
    """Supported accelerator types."""
    CUDA = "cuda"
    MPS = "mps"  # Apple Silicon
    CPU = "cpu"


@dataclass
class DeviceInfo:
    """
    Information about a specific hardware device.
    
    Attributes:
        device_id: Numeric identifier for the device
        name: Human-readable device name
        memory_total_gb: Total device memory in gigabytes
        memory_available_gb: Available device memory in gigabytes
        compute_capability: Optional tuple of (major, minor) compute capability
        accelerator_type: Type of accelerator (CUDA, MPS, or CPU)
    """
    device_id: int
    name: str
    memory_total_gb: float
    memory_available_gb: float
    compute_capability: Optional[float] = None
    accelerator_type: AcceleratorType = AcceleratorType.CPU


@dataclass
class AcceleratorConfig:
    """
    Configuration for accelerator usage.
    
    Attributes:
        device: Device identifier string (e.g., "cuda:0", "cpu")
        device_id: Numeric device identifier
        accelerator_type: Type of accelerator
        available_devices: Number of available devices of this type
        memory_info: Optional dictionary with memory usage information
    """
    device: str
    device_id: int
    accelerator_type: AcceleratorType
    available_devices: int
    memory_info: Optional[Dict[str, float]] = None
