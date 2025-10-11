#!/usr/bin/env python3
"""
Test script for GPU utilities to verify accelerator detection and platform-aware selection.

This script tests the hardware acceleration detection and configuration system,
verifying that the system correctly identifies available accelerators (CUDA, MPS, CPU)
and configures them appropriately for document processing.

Usage:
    python gpu_diagnostics.py

The script will output detailed information about:
- Available accelerators (CUDA, MPS, CPU)
- Platform-specific optimal accelerator selection
- Device configurations for different frameworks
- CUDA/MPS availability and device information
"""

import logging
import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Configure logging to see debug messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_gpu_utils():
    """Test the GPU utilities functionality."""
    print("=" * 60)
    print("TESTING GPU UTILITIES")
    print("=" * 60)
    
    try:
        # Import the GPU utilities
        from doc2md_conversion_engine.utils.gpu_utils import (
            get_accelerator_detector,
            detect_optimal_device,
            is_gpu_acceleration_available,
            log_accelerator_info
        )
        
        print("\n1. Testing AcceleratorDetector initialization...")
        detector = get_accelerator_detector()
        print("✓ AcceleratorDetector initialized successfully")
        
        print("\n2. Testing accelerator detection...")
        available_accelerators = detector.detect_available_accelerators()
        print(f"Available accelerators: {available_accelerators}")
        
        print("\n3. Testing platform-optimal accelerator selection...")
        platform_optimal = detector._get_platform_optimal_accelerator()
        print(f"Platform-optimal accelerator: {platform_optimal}")
        
        print("\n4. Testing optimal device configuration...")
        optimal_config = detector.get_optimal_device_config()
        print(f"Optimal device config: {optimal_config}")
        
        print("\n5. Testing Docling accelerator config...")
        docling_config = detector.get_docling_accelerator_config()
        print(f"Docling accelerator config: {docling_config}")
        
        print("\n6. Testing convenience functions...")
        optimal_device = detect_optimal_device()
        gpu_available = is_gpu_acceleration_available()
        print(f"Optimal device: {optimal_device}")
        print(f"GPU acceleration available: {gpu_available}")
        
        print("\n7. Testing CUDA detection specifically...")
        cuda_available = detector._detect_cuda_availability()
        print(f"CUDA available: {cuda_available}")
        
        if cuda_available:
            print("\n8. Testing CUDA device info...")
            try:
                # Import AcceleratorType directly from the models module
                from doc2md_conversion_engine.models.accelerator import AcceleratorType
                cuda_devices = detector.get_device_info(AcceleratorType.CUDA)
                print(f"CUDA devices: {cuda_devices}")
                
                # Print detailed device information
                for device in cuda_devices:
                    print(f"  - Device {device.device_id}: {device.name}")
                    print(f"    Memory: {device.memory_total_gb:.2f}GB total, {device.memory_available_gb:.2f}GB available")
                    if device.compute_capability:
                        print(f"    Compute Capability: {device.compute_capability}")
            except Exception as e:
                print(f"Error getting CUDA device info: {e}")
        
        print("\n9. Testing MPS detection...")
        mps_available = detector._detect_mps_availability()
        print(f"MPS available: {mps_available}")
        
        if mps_available:
            try:
                from doc2md_conversion_engine.models.accelerator import AcceleratorType
                mps_devices = detector.get_device_info(AcceleratorType.MPS)
                print(f"MPS devices: {mps_devices}")
            except Exception as e:
                print(f"Error getting MPS device info: {e}")
        
        print("\n10. Testing comprehensive logging...")
        detector.log_accelerator_info()
        
        print("\n" + "=" * 60)
        print("GPU UTILITIES TEST COMPLETED SUCCESSFULLY")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_gpu_utils()
    sys.exit(0 if success else 1)
