#!/usr/bin/env python3
"""
GPU and hardware acceleration utilities for document processing.

This module provides comprehensive utilities for detecting and configuring 
hardware acceleration across multiple platforms and ML frameworks. It supports
CUDA, MPS (Apple Silicon), and CPU fallback with intelligent device
selection and robust error handling.

================================================================================
DOCLING INTEGRATION OVERVIEW
================================================================================

This module is the FOUNDATION for Docling hardware acceleration integration:

1. ACCELERATOR DETECTION:
   - Detects available hardware (CUDA GPU, MPS Apple Silicon, CPU)
   - Performs platform-aware selection (Windows->CUDA, macOS->MPS)
   - Tests actual device functionality (not just availability)

2. DOCLING CONFIGURATION:
   - get_docling_accelerator_config() provides Docling-specific configuration
   - Maps internal AcceleratorConfig to Docling's expected format
   - Returns configuration used by ContentExtractor._initialize_docling()

3. INTEGRATION FLOW:
   DocumentProcessingConfig.get_device_config() 
   -> AcceleratorDetector.get_docling_accelerator_config()
   -> ContentExtractor._initialize_docling()
   -> Docling PdfPipelineOptions with accelerator configuration
   -> Docling uses selected hardware for all document processing

4. HARDWARE ACCELERATION IMPACT:
   - CUDA: GPU-accelerated OCR, image processing, document conversion
   - MPS: Apple Silicon-accelerated processing on M1/M2/M3 chips
   - CPU: Fallback processing when no GPU acceleration available

Key Features:
- Multi-platform accelerator detection (CUDA, MPS)
- Environment-based device configuration
- Thread-safe singleton pattern
- Comprehensive logging and debugging
- Automatic fallback mechanisms
- Memory and performance monitoring
- Direct Docling integration support

Example:
    >>> from doc2md_conversion_engine.utils.gpu_utils import get_accelerator_detector
    >>> detector = get_accelerator_detector()
    >>> device_config = detector.get_optimal_device_config()
    >>> print(f"Using device: {device_config.device}")
    
    # For Docling integration:
    >>> docling_config = detector.get_docling_accelerator_config()
    >>> print(f"Docling accelerator: {docling_config['accelerator']}")
"""

import logging
import os
import threading
from typing import Optional, Dict, Any, List

from ..models.accelerator import AcceleratorType, DeviceInfo, AcceleratorConfig

logger = logging.getLogger(__name__)


class AcceleratorDetector:
    """
    Comprehensive accelerator detection and configuration utility.
    
    This class provides robust detection and configuration of hardware
    accelerators across multiple platforms. It supports CUDA, ROCm, MPS
    (Apple Silicon), and CPU fallback with intelligent device selection.
    
    Features:
    - Multi-platform accelerator detection
    - Environment-based configuration
    - Thread-safe operations
    - Comprehensive error handling
    - Memory and performance monitoring
    - Automatic fallback mechanisms
    """
    
    # Environment variable constants
    FORCE_CPU_ENV = "FORCE_CPU"
    PREFERRED_DEVICE_ENV = "PREFERRED_DEVICE"
    CUDA_VISIBLE_DEVICES_ENV = "CUDA_VISIBLE_DEVICES"
    CUDA_DEVICE_ID_ENV = "CUDA_DEVICE_ID"
    
    # Default values
    DEFAULT_DEVICE_ID = 0
    MEMORY_CONVERSION_FACTOR = 1024 ** 3  # Bytes to GB

    def __init__(self) -> None:
        """
        Initialize the accelerator detector.
        
        Sets up internal state and prepares for lazy-loaded detection of
        available accelerators to avoid expensive operations during initialization.
        """
        self._detected_accelerators: Dict[AcceleratorType, bool] = {}
        self._device_info_cache: Dict[AcceleratorType, List[DeviceInfo]] = {}
        self._preferred_device: Optional[str] = None
        self._lock = threading.RLock()

        logger.debug("AcceleratorDetector initialized")

    def detect_available_accelerators(self) -> Dict[AcceleratorType, bool]:
        """
        Detect all available accelerator types on the system.

        Returns:
            Dictionary mapping accelerator types to availability status
            
        Note:
            This method is thread-safe and caches results for performance.
        """
        with self._lock:
            if not self._detected_accelerators:
                self._detected_accelerators = {
                    AcceleratorType.CUDA: self._detect_cuda_availability(),
                    AcceleratorType.MPS: self._detect_mps_availability(),
                    AcceleratorType.CPU: True  # CPU is always available
                }
                
                available_count = sum(1 for available in self._detected_accelerators.values() if available)
                logger.info(f"Detected {available_count} accelerator type(s) available")
                
            return self._detected_accelerators.copy()
    
    def _detect_cuda_availability(self) -> bool:
        """
        Detect CUDA availability with comprehensive error handling.

        Returns:
            True if CUDA is available and functional, False otherwise
            
        Note:
            Performs basic CUDA functionality test to ensure device is usable.
            Logs detailed information about detection process for debugging.
        """
        try:
            import torch
            logger.debug(f"PyTorch version: {torch.__version__}")
            
            # Check if CUDA is available in PyTorch
            cuda_available = torch.cuda.is_available()
            if not cuda_available:
                logger.debug("PyTorch reports CUDA not available")
                return False
            
            logger.debug("PyTorch reports CUDA is available")
                
            # Test basic CUDA functionality
            device_count = torch.cuda.device_count()
            if device_count == 0:
                logger.debug("No CUDA devices found despite torch.cuda.is_available() returning True")
                return False
            
            logger.debug(f"CUDA device count: {device_count}")
                
            # Test device access with more robust error handling
            try:
                # Try to create a simple tensor on CUDA device
                logger.debug("Attempting to create test tensor on CUDA device")
                test_tensor = torch.tensor([1.0], device="cuda:0")
                
                # Try a simple operation to verify functionality
                result = test_tensor * 2
                
                # Get device name for logging
                device_name = torch.cuda.get_device_name(0)
                logger.debug(f"CUDA device name: {device_name}")
                
                # Clean up
                del test_tensor, result
                torch.cuda.empty_cache()
                
                logger.info(f"CUDA available and functional: {device_count} device(s)")
                return True
            except Exception as e:
                logger.warning(f"CUDA devices detected but not functional: {e}")
                logger.debug("This could be due to driver issues or CUDA version mismatch")
                return False
                
        except ImportError:
            logger.debug("PyTorch not available for CUDA detection")
            return False
        except Exception as e:
            logger.warning(f"Unexpected error during CUDA detection: {e}")
            return False

    def _detect_mps_availability(self) -> bool:
        """
        Detect MPS availability for Apple Silicon.
        
        Returns:
            True if MPS is available, False otherwise
            
        Note:
            MPS (Metal Performance Shaders) is Apple's GPU acceleration framework
            for Apple Silicon (M1/M2/M3) chips.
        """
        try:
            import torch
            if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                logger.info("MPS (Apple Silicon) available")
                return True
            return False
        except ImportError:
            logger.debug("PyTorch not available for MPS detection")
            return False
        except Exception as e:
            logger.debug(f"MPS detection failed: {e}")
            return False

    def get_device_info(self, accelerator_type: AcceleratorType) -> List[DeviceInfo]:
        """
        Get detailed information about devices for a specific accelerator type.
        
        Args:
            accelerator_type: Type of accelerator to query

        Returns:
            List of DeviceInfo objects for available devices
            
        Note:
            Results are cached for performance. Subsequent calls return cached data.
        """
        with self._lock:
            if accelerator_type not in self._device_info_cache:
                self._device_info_cache[accelerator_type] = self._query_device_info(accelerator_type)
            return self._device_info_cache[accelerator_type].copy()
    
    def _query_device_info(self, accelerator_type: AcceleratorType) -> List[DeviceInfo]:
        """
        Query detailed device information for a specific accelerator type.
        
        Args:
            accelerator_type: Type of accelerator to query

        Returns:
            List of DeviceInfo objects
            
        Note:
            Internal method that dispatches to type-specific query methods.
        """
        devices: List[DeviceInfo] = []
        
        try:
            if accelerator_type == AcceleratorType.CUDA:
                devices = self._query_cuda_device_info()
            elif accelerator_type == AcceleratorType.MPS:
                devices = self._query_mps_device_info()
            elif accelerator_type == AcceleratorType.CPU:
                devices = self._query_cpu_device_info()
                
        except Exception as e:
            logger.warning(f"Failed to query device info for {accelerator_type.value}: {e}")
            
        return devices
    
    def _query_cuda_device_info(self) -> List[DeviceInfo]:
        """
        Query detailed information about CUDA devices.

        Returns:
            List of DeviceInfo objects for CUDA devices
            
        Note:
            Queries memory information, compute capability, and device properties
            for all available CUDA devices.
        """
        try:
            import torch
            devices: List[DeviceInfo] = []
            
            for device_id in range(torch.cuda.device_count()):
                device_props = torch.cuda.get_device_properties(device_id)
                memory_total = device_props.total_memory / self.MEMORY_CONVERSION_FACTOR
                
                # Get available memory
                torch.cuda.set_device(device_id)
                memory_available = (device_props.total_memory - torch.cuda.memory_allocated(device_id)) / self.MEMORY_CONVERSION_FACTOR
                
                device_info = DeviceInfo(
                    device_id=device_id,
                    name=device_props.name,
                    memory_total_gb=memory_total,
                    memory_available_gb=memory_available,
                    compute_capability=device_props.major + device_props.minor / 10,
                    accelerator_type=AcceleratorType.CUDA
                )
                devices.append(device_info)
                
            return devices
            
        except Exception as e:
            logger.warning(f"Failed to query CUDA device info: {e}")
            return []
    
    def _query_mps_device_info(self) -> List[DeviceInfo]:
        """
        Query MPS device information.

        Returns:
            List of DeviceInfo objects for MPS devices
            
        Note:
            Currently returns empty list as MPS device info querying is not
            yet fully implemented. This is a placeholder for future enhancement.
        """
        # TODO: Implement detailed MPS device info querying
        # MPS doesn't provide as detailed info as CUDA through PyTorch
        return []
    
    def _query_cpu_device_info(self) -> List[DeviceInfo]:
        """
        Query CPU device information.
        
        Returns:
            List containing a single DeviceInfo object for the CPU
            
        Note:
            Uses psutil if available for accurate memory information,
            otherwise returns placeholder values.
        """
        try:
            import psutil
            memory_total = psutil.virtual_memory().total / self.MEMORY_CONVERSION_FACTOR
            memory_available = psutil.virtual_memory().available / self.MEMORY_CONVERSION_FACTOR
            
            return [DeviceInfo(
                device_id=0,
                name="CPU",
                memory_total_gb=memory_total,
                memory_available_gb=memory_available,
                accelerator_type=AcceleratorType.CPU
            )]
        except ImportError:
            logger.debug("psutil not available for CPU memory info")
            return [DeviceInfo(
                device_id=0,
                name="CPU",
                memory_total_gb=0.0,
                memory_available_gb=0.0,
                accelerator_type=AcceleratorType.CPU
            )]
            
    def _get_platform_optimal_accelerator(self) -> str:
        """
        Get the optimal accelerator for the current platform.

        Returns:
            Optimal accelerator type for the platform
            
        Note:
            Uses platform-specific defaults:
            - Windows/Linux: CUDA preferred
            - macOS: MPS (Apple Silicon) preferred
            - All platforms: CPU as fallback
        """
        import platform
        system = platform.system().lower()
        
        logger.debug(f"Detected platform: {system}")
        
        if system == "darwin":  # macOS
            # Prefer MPS on Apple Silicon, fallback to CPU
            logger.debug("macOS detected, checking for MPS (Apple Silicon) support")
            if self._detect_mps_availability():
                logger.debug("MPS support detected on macOS")
                return "mps"
            logger.debug("No MPS support on macOS, using CPU")
            return "cpu"
        elif system in ["windows", "linux"]:
            # Prefer CUDA on Windows/Linux, fallback to CPU
            logger.debug(f"{system.capitalize()} detected, checking for CUDA support")
            if self._detect_cuda_availability():
                logger.debug(f"CUDA support detected on {system}")
                return "cuda"
            logger.debug(f"No CUDA support on {system}, using CPU")
            return "cpu"
        else:  # Other systems
            # Prefer CUDA, fallback to CPU
            logger.debug(f"Unknown platform: {system}, checking for CUDA support")
            if self._detect_cuda_availability():
                return "cuda"
            return "cpu"
    
    def get_optimal_device_config(self) -> AcceleratorConfig:
        """
        Get the optimal device configuration based on availability and preferences.

        Returns:
            AcceleratorConfig object with optimal device settings
            
        Note:
            Considers environment variables, hardware availability, and performance
            characteristics to select the best device.
        """
        with self._lock:
            if self._preferred_device is None:
                self._preferred_device = self._determine_optimal_device()
            
            return self._create_device_config(self._preferred_device)
    
    def _determine_optimal_device(self) -> str:
        """
        Determine the optimal device based on environment and availability.

        This method is the CORE of our Docling integration strategy. It determines
        which accelerator (CUDA/MPS/CPU) will be used by Docling for document processing.
        
        The selected device directly impacts:
        - Docling's PdfPipelineOptions configuration
        - PyTorch backend device selection within Docling
        - Document processing performance (GPU vs CPU)
        - Memory usage patterns (VRAM vs RAM)

        Returns:
            Optimal device string ('cuda', 'mps', or 'cpu')
            
        Note:
            Selection priority designed for optimal Docling performance:
            1. Environment override (force CPU) - for debugging/testing
            2. Explicit device preference - user override
            3. Platform-specific optimal accelerator - intelligent defaults
            4. CPU fallback - always works
        """
        # Priority 1: Check for explicit CPU forcing
        # This allows users to force CPU mode for Docling via FORCE_CPU=true
        if self._is_cpu_forced():
            logger.info("CPU usage forced via environment variable - Docling will use CPU")
            return "cpu"

        # Priority 2: Check for explicit device preference
        # This allows users to explicitly request CUDA/MPS for Docling via PREFERRED_DEVICE
        explicit_device = self._get_explicit_device_preference()
        if explicit_device and self._is_device_available(explicit_device):
            logger.info(f"Using explicitly requested device for Docling: {explicit_device}")
            return explicit_device
            
        # Priority 3: Use platform-specific optimal accelerator
        # This is where our intelligent Docling integration happens:
        # - Windows/Linux: Prefer CUDA for GPU acceleration in Docling
        # - macOS: Prefer MPS for Apple Silicon acceleration in Docling
        # - All platforms: Fall back to CPU if GPU not available
        logger.info("Using platform-aware accelerator selection for Docling")
        platform_optimal = self._get_platform_optimal_accelerator()
        
        # Log the selected accelerator for Docling integration
        if platform_optimal == "cuda":
            logger.info("Platform-optimized selection for Docling: CUDA (GPU acceleration enabled)")
        elif platform_optimal == "mps":
            logger.info("Platform-optimized selection for Docling: MPS (Apple Silicon acceleration enabled)")
        else:
            logger.info("Platform-optimized selection for Docling: CPU (no GPU acceleration)")
            
        return platform_optimal
    
    def _is_cpu_forced(self) -> bool:
        """
        Check if CPU usage is forced via environment variable.
        
        Returns:
            True if CPU usage is forced, False otherwise
            
        Note:
            Checks FORCE_CPU environment variable for values: true, 1, yes (case-insensitive)
        """
        return os.getenv(self.FORCE_CPU_ENV, "false").lower() in ("true", "1", "yes")
    
    def _get_explicit_device_preference(self) -> Optional[str]:
        """
        Get explicit device preference from environment variables.
        
        Returns:
            Device preference string or None if not set
            
        Note:
            Reads from PREFERRED_DEVICE environment variable
        """
        pref = os.getenv(self.PREFERRED_DEVICE_ENV, "").lower()
        return pref if pref else None
    
    def _is_device_available(self, device: str) -> bool:
        """
        Check if a specific device type is available.
        
        Args:
            device: Device type string ('cuda', 'mps', or 'cpu')
            
        Returns:
            True if the device is available, False otherwise
        """
        available_accelerators = self.detect_available_accelerators()
        
        if device == "cuda":
            return available_accelerators.get(AcceleratorType.CUDA, False)
        elif device == "mps":
            return available_accelerators.get(AcceleratorType.MPS, False)
        elif device == "cpu":
            return True
        
        return False
    
    def _create_device_config(self, device: str) -> AcceleratorConfig:
        """
        Create device configuration for the specified device.
        
        Args:
            device: Device type string ('cuda', 'mps', or 'cpu')

        Returns:
            AcceleratorConfig object with device-specific settings
        """
        if device == "cuda":
            return self._create_cuda_config()
        elif device == "mps":
            return self._create_mps_config()
        else:
            return self._create_cpu_config()

    def _create_cuda_config(self) -> AcceleratorConfig:
        """
        Create CUDA device configuration.

        Returns:
            AcceleratorConfig for CUDA device, falls back to CPU on error
            
        Note:
            Reads CUDA_DEVICE_ID environment variable for device selection,
            validates device availability, and queries memory information.
        """
        try:
            import torch
            device_id = int(os.getenv(self.CUDA_DEVICE_ID_ENV, str(self.DEFAULT_DEVICE_ID)))
            device_count = torch.cuda.device_count()
            
            # Validate device ID
            if device_id >= device_count:
                logger.warning(f"CUDA device {device_id} not available, using device 0")
                device_id = 0
            
            device_string = f"cuda:{device_id}"
            
            # Get memory info
            memory_info: Optional[Dict[str, float]] = None
            try:
                torch.cuda.set_device(device_id)
                props = torch.cuda.get_device_properties(device_id)
                memory_info = {
                    "total_gb": props.total_memory / self.MEMORY_CONVERSION_FACTOR,
                    "allocated_gb": torch.cuda.memory_allocated(device_id) / self.MEMORY_CONVERSION_FACTOR,
                    "reserved_gb": torch.cuda.memory_reserved(device_id) / self.MEMORY_CONVERSION_FACTOR
                }
            except Exception as e:
                logger.debug(f"Could not get CUDA memory info: {e}")
            
            return AcceleratorConfig(
                device=device_string,
                device_id=device_id,
                accelerator_type=AcceleratorType.CUDA,
                available_devices=device_count,
                memory_info=memory_info
            )
            
        except Exception as e:
            logger.warning(f"Error creating CUDA config: {e}, falling back to CPU")
            return self._create_cpu_config()
    
    def _create_mps_config(self) -> AcceleratorConfig:
        """
        Create MPS device configuration.

        Returns:
            AcceleratorConfig for MPS device
            
        Note:
            Currently returns basic MPS configuration. Full MPS support
            including memory info is pending PyTorch API enhancements.
        """
        # TODO: Add detailed MPS configuration when PyTorch provides better APIs
        return AcceleratorConfig(
            device="mps",
            device_id=0,
            accelerator_type=AcceleratorType.MPS,
            available_devices=1
        )
    
    def _create_cpu_config(self) -> AcceleratorConfig:
        """
        Create CPU device configuration.
        
        Returns:
            AcceleratorConfig for CPU
        """
        return AcceleratorConfig(
            device="cpu",
            device_id=0,
            accelerator_type=AcceleratorType.CPU,
            available_devices=1
        )

    def get_docling_accelerator_config(self) -> Dict[str, Any]:
        """
        Get Docling-specific accelerator configuration.
        
        This is the CRITICAL integration point between our accelerator detection
        and Docling's document processing pipeline. This method:
        
        1. Gets the optimal device configuration from our platform-aware detector
        2. Maps our internal AcceleratorConfig to Docling's expected format
        3. Provides the exact configuration that Docling needs for hardware acceleration
        
        The returned dictionary is used by ContentExtractor._initialize_docling() to:
        - Configure Docling's PdfPipelineOptions with the correct accelerator
        - Set device-specific parameters (CUDA device ID, MPS settings, etc.)
        - Enable GPU/MPS acceleration for document processing tasks

        Returns:
            Dictionary with Docling-compatible accelerator settings containing:
            - accelerator: Type of accelerator ('cuda', 'mps', 'cpu')
            - device: Device string for PyTorch ('cuda:0', 'mps', 'cpu')
            - device_id: Numeric device identifier
            - available_devices: Number of available devices of this type
            
        Note:
            This method is the bridge between our intelligent accelerator detection
            and Docling's document processing. It ensures Docling uses the optimal
            hardware acceleration available on the system.
        """
        # Get the optimal device configuration from our platform-aware detector
        # This considers: platform (Windows->CUDA, macOS->MPS), availability, environment overrides
        optimal_config = self.get_optimal_device_config()
        
        # Map our internal AcceleratorConfig to Docling's expected format
        # This is where the integration happens - we convert our detection results
        # into the exact format that Docling expects for hardware acceleration
        if optimal_config.accelerator_type == AcceleratorType.CUDA:
            # CUDA configuration for Docling
            # Docling will use this to enable CUDA acceleration for document processing
            return {
                "accelerator": "cuda",  # Tells Docling to use CUDA
                "device": optimal_config.device,  # e.g., "cuda:0" for PyTorch
                "device_id": optimal_config.device_id,  # Specific GPU device ID
                "available_devices": optimal_config.available_devices  # Total CUDA devices
            }
        elif optimal_config.accelerator_type == AcceleratorType.MPS:
            # MPS configuration for Apple Silicon
            # Docling will use this to enable MPS acceleration on Apple Silicon
            return {
                "accelerator": "mps",  # Tells Docling to use MPS
                "device": "mps",  # MPS device string for PyTorch
                "device_id": 0,  # MPS typically uses device 0
                "available_devices": 1  # Apple Silicon has one MPS device
            }
        else:  # CPU fallback
            # CPU configuration when no GPU acceleration is available
            # Docling will process documents using CPU-only mode
            return {
                "accelerator": "cpu",  # Tells Docling to use CPU
                "device": "cpu",  # CPU device string for PyTorch
                "device_id": 0,  # CPU is always device 0
                "available_devices": 1  # One CPU device
            }

    def log_accelerator_info(self) -> None:
        """
        Log comprehensive information about detected accelerators.
        
        This method logs detailed information about all available accelerators,
        their capabilities, and the current configuration. Useful for debugging
        and system diagnostics.
        """
        logger.info("=" * 60)
        logger.info("ACCELERATOR DETECTION REPORT")
        logger.info("=" * 60)
        
        # Log available accelerators
        available_accelerators = self.detect_available_accelerators()
        logger.info("Available Accelerators:")
        for accel_type, is_available in available_accelerators.items():
            status = "✓" if is_available else "✗"
            logger.info(f"  {status} {accel_type.value.upper()}")
        
        # Log device details
        for accel_type in available_accelerators:
            if available_accelerators[accel_type]:
                devices = self.get_device_info(accel_type)
                if devices:
                    logger.info(f"\n{accel_type.value.upper()} Devices:")
                    for device in devices:
                        logger.info(f"  Device {device.device_id}: {device.name}")
                        logger.info(f"    Memory: {device.memory_total_gb:.1f}GB total, {device.memory_available_gb:.1f}GB available")
                        if device.compute_capability:
                            logger.info(f"    Compute Capability: {device.compute_capability}")
        
        # Log current configuration
        config = self.get_optimal_device_config()
        logger.info(f"\nSelected Configuration:")
        logger.info(f"  Device: {config.device}")
        logger.info(f"  Accelerator Type: {config.accelerator_type.value}")
        logger.info(f"  Available Devices: {config.available_devices}")
        if config.memory_info:
            logger.info(f"  Memory Info: {config.memory_info}")
        
        # Log environment variables
        logger.info(f"\nEnvironment Variables:")
        env_vars = [
            self.FORCE_CPU_ENV,
            self.PREFERRED_DEVICE_ENV,
            self.CUDA_VISIBLE_DEVICES_ENV,
            self.CUDA_DEVICE_ID_ENV
        ]
        for env_var in env_vars:
            value = os.getenv(env_var, "not set")
            logger.info(f"  {env_var}: {value}")
        
        logger.info("=" * 60)


# Thread-safe singleton pattern
_accelerator_detector: Optional[AcceleratorDetector] = None
_detector_lock = threading.Lock()


def get_accelerator_detector() -> AcceleratorDetector:
    """
    Get the global accelerator detector instance (thread-safe singleton).

    Returns:
        AcceleratorDetector instance
        
    Note:
        Uses double-checked locking pattern for thread-safe singleton initialization.
    """
    global _accelerator_detector
    
    if _accelerator_detector is None:
        with _detector_lock:
            if _accelerator_detector is None:
                _accelerator_detector = AcceleratorDetector()
                logger.debug("Created global AcceleratorDetector instance")
    
    return _accelerator_detector


def detect_optimal_device() -> str:
    """
    Convenience function to detect the optimal device for processing.

    Returns:
        Optimal device string ('cuda:0', 'mps', or 'cpu')
        
    Example:
        >>> device = detect_optimal_device()
        >>> print(f"Using device: {device}")
    """
    return get_accelerator_detector().get_optimal_device_config().device


def is_gpu_acceleration_available() -> bool:
    """
    Check if GPU acceleration is available and will be used.

    Returns:
        True if GPU acceleration will be used, False otherwise
        
    Example:
        >>> if is_gpu_acceleration_available():
        ...     print("GPU acceleration enabled")
    """
    config = get_accelerator_detector().get_optimal_device_config()
    return config.accelerator_type != AcceleratorType.CPU


def get_device_config_for_framework(framework: str) -> Dict[str, Any]:
    """
    Get device configuration optimized for a specific ML framework.
    
    Args:
        framework: Target framework ('pytorch', 'tensorflow', 'docling')
        
    Returns:
        Dictionary with framework-specific device configuration
        
    Example:
        >>> config = get_device_config_for_framework('pytorch')
        >>> model.to(config['device'])
    """
    config = get_accelerator_detector().get_optimal_device_config()
    
    if framework.lower() == "pytorch":
        return {
            "device": config.device,
            "device_id": config.device_id,
            "available_devices": config.available_devices
        }
    elif framework.lower() == "tensorflow":
        return {
            "device": config.device,
            "visible_devices": f"{config.device_id}" if config.accelerator_type != AcceleratorType.CPU else "-1"
        }
    elif framework.lower() == "docling":
        return {
            "accelerator": config.accelerator_type.value,
            "device": config.device,
            "device_id": config.device_id
        }
    else:
        logger.warning(f"Unknown framework '{framework}', returning generic config")
        return {"device": config.device}


def log_accelerator_info() -> None:
    """
    Log comprehensive accelerator information for debugging.
    
    Example:
        >>> log_accelerator_info()
        # Outputs detailed accelerator report to logs
    """
    get_accelerator_detector().log_accelerator_info()


# Backward compatibility aliases
GPUDetector = AcceleratorDetector
get_gpu_detector = get_accelerator_detector