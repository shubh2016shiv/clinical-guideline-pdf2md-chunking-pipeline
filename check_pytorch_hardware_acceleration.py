#!/usr/bin/env python3
"""
Quick script to check PyTorch installation and hardware acceleration availability.

This script provides a simple way to verify that PyTorch is installed correctly
and that hardware acceleration (CUDA or MPS) is available and working.

Usage:
    python check_pytorch_hardware_acceleration.py [--verbose] [--device DEVICE_ID]
    
Options:
    --verbose: Show detailed information including all GPU devices
    --device DEVICE_ID: Test specific CUDA device (default: 0)
"""

import sys
import platform
import argparse
from typing import Optional, List, Tuple


def check_pytorch(verbose: bool = False, device_id: int = 0) -> None:
    """
    Check PyTorch installation and hardware acceleration availability.
    
    Args:
        verbose: If True, show detailed information for all devices
        device_id: Specific CUDA device ID to test (default: 0)
    """
    print("=" * 60)
    print("PYTORCH INSTALLATION AND HARDWARE ACCELERATION CHECK")
    print("=" * 60)
    
    # System information
    _print_system_info()
    
    # Check PyTorch installation
    try:
        import torch
        torchvision_ok = _print_pytorch_info(torch)
        
        if not torchvision_ok:
            print("\n✗ Torchvision is required but not installed!")
            print("  Please install Torchvision using the instructions in INSTALLATION.md")
            return
        
        # Check CUDA availability
        cuda_available = _check_cuda_availability(torch, verbose, device_id)
        
        # Check MPS availability (Apple Silicon)
        mps_available = _check_mps_availability(torch)
        
        # Summary
        _print_acceleration_summary(torch, cuda_available, mps_available)
        
    except ImportError:
        print("\n✗ PyTorch is not installed!")
        print("  Please install PyTorch using the instructions in INSTALLATION.md")
        print("  Visit: https://pytorch.org/get-started/locally/")
    except Exception as e:
        print(f"\n✗ Error checking PyTorch installation: {e}")
        if verbose:
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)


def _print_system_info() -> None:
    """Print system information including Python version and platform."""
    print(f"\nSystem Information:")
    print(f"  Python version: {sys.version.split()[0]}")
    print(f"  Platform: {platform.platform()}")
    print(f"  Architecture: {platform.machine()}")
    print(f"  Processor: {platform.processor() or 'Unknown'}")


def _print_pytorch_info(torch) -> None:
    """
    Print PyTorch and Torchvision installation information.
    
    Args:
        torch: PyTorch module
    """
    print(f"\nPyTorch Installation:")
    print(f"  PyTorch version: {torch.__version__}")
    print(f"  Install path: {torch.__file__}")
    
    # Check Torchvision
    try:
        import torchvision
        print(f"  Torchvision version: {torchvision.__version__}")
        print(f"  Torchvision install path: {torchvision.__file__}")
    except ImportError:
        print("  ✗ Torchvision not installed (required by Docling)")
        return False
    
    # Print backend information
    if hasattr(torch, 'version') and hasattr(torch.version, 'cuda'):
        print(f"  Built with CUDA: {torch.version.cuda or 'No'}")
    if hasattr(torch, 'version') and hasattr(torch.version, 'hip'):
        print(f"  Built with ROCm: {torch.version.hip or 'No'}")
    
    return True


def _check_cuda_availability(torch, verbose: bool, device_id: int) -> bool:
    """
    Check CUDA availability and test functionality.
    
    Args:
        torch: PyTorch module
        verbose: If True, show information for all devices
        device_id: Specific device ID to test
        
    Returns:
        True if CUDA is available and working, False otherwise
    """
    print(f"\nCUDA Acceleration:")
    cuda_available = torch.cuda.is_available()
    print(f"  CUDA available: {cuda_available}")
    
    if not cuda_available:
        return False
    
    try:
        print(f"  CUDA version: {torch.version.cuda}")
        device_count = torch.cuda.device_count()
        print(f"  CUDA device count: {device_count}")
        
        if device_count == 0:
            print("  ✗ No CUDA devices found")
            return False
        
        # Validate requested device ID
        if device_id >= device_count:
            print(f"  ⚠ Requested device {device_id} not available, using device 0")
            device_id = 0
        
        # Show all devices if verbose
        if verbose:
            _print_all_cuda_devices(torch, device_count)
        else:
            # Show only the primary device
            _print_cuda_device_info(torch, device_id)
        
        # Test CUDA functionality on specified device
        success = _test_cuda_device(torch, device_id)
        
        if success:
            print(f"  ✓ CUDA is working correctly on device {device_id}!")
        else:
            print(f"  ✗ CUDA test failed on device {device_id}")
            
        return success
        
    except Exception as e:
        print(f"  ✗ CUDA check failed: {e}")
        return False


def _print_all_cuda_devices(torch, device_count: int) -> None:
    """
    Print information for all CUDA devices.
    
    Args:
        torch: PyTorch module
        device_count: Number of CUDA devices
    """
    print(f"\n  All CUDA Devices:")
    for i in range(device_count):
        _print_cuda_device_info(torch, i, indent="    ")


def _print_cuda_device_info(torch, device_id: int, indent: str = "  ") -> None:
    """
    Print information for a specific CUDA device.
    
    Args:
        torch: PyTorch module
        device_id: Device ID to query
        indent: String indentation for output
    """
    try:
        props = torch.cuda.get_device_properties(device_id)
        print(f"{indent}Device {device_id}: {props.name}")
        print(f"{indent}  Compute capability: {props.major}.{props.minor}")
        print(f"{indent}  Total memory: {props.total_memory / 1024**3:.2f} GB")
        print(f"{indent}  Multi-processors: {props.multi_processor_count}")
    except Exception as e:
        print(f"{indent}Device {device_id}: Error querying device - {e}")


def _test_cuda_device(torch, device_id: int) -> bool:
    """
    Test CUDA device functionality with basic operations.
    
    Args:
        torch: PyTorch module
        device_id: Device ID to test
        
    Returns:
        True if test passed, False otherwise
    """
    try:
        device = torch.device(f"cuda:{device_id}")
        
        # Basic tensor operations
        x = torch.tensor([1.0, 2.0, 3.0], device=device)
        y = x * 2
        result = y.cpu().numpy()
        
        # Verify results
        expected = [2.0, 4.0, 6.0]
        if not all(abs(a - b) < 1e-6 for a, b in zip(result, expected)):
            print(f"  ✗ CUDA computation error: expected {expected}, got {result.tolist()}")
            return False
        
        print(f"  CUDA test result: {result.tolist()}")
        
        # Memory information
        torch.cuda.set_device(device_id)
        allocated = torch.cuda.memory_allocated(device_id) / 1024**2
        reserved = torch.cuda.memory_reserved(device_id) / 1024**2
        print(f"  Memory allocated: {allocated:.2f} MB")
        print(f"  Memory reserved: {reserved:.2f} MB")
        
        # Cleanup
        del x, y
        torch.cuda.empty_cache()
        
        return True
        
    except Exception as e:
        print(f"  ✗ CUDA test failed: {e}")
        return False


def _check_mps_availability(torch) -> bool:
    """
    Check MPS (Apple Silicon) availability and test functionality.
    
    Args:
        torch: PyTorch module
        
    Returns:
        True if MPS is available and working, False otherwise
    """
    print(f"\nMPS Acceleration (Apple Silicon):")
    
    if not hasattr(torch.backends, "mps"):
        print("  MPS not supported in this PyTorch build")
        print("  (MPS requires PyTorch 1.12+ on macOS 12.3+)")
        return False
    
    mps_available = torch.backends.mps.is_available()
    print(f"  MPS available: {mps_available}")
    
    if not mps_available:
        if hasattr(torch.backends.mps, "is_built"):
            is_built = torch.backends.mps.is_built()
            print(f"  MPS built: {is_built}")
            if is_built:
                print("  MPS is built but not available (check macOS version)")
        return False
    
    # Test MPS functionality
    try:
        device = torch.device("mps")
        x = torch.tensor([1.0, 2.0, 3.0], device=device)
        y = x * 2
        result = y.cpu().numpy()
        
        # Verify results
        expected = [2.0, 4.0, 6.0]
        if not all(abs(a - b) < 1e-6 for a, b in zip(result, expected)):
            print(f"  ✗ MPS computation error: expected {expected}, got {result.tolist()}")
            return False
        
        print(f"  MPS test result: {result.tolist()}")
        print("  ✓ MPS is working correctly!")
        
        # Cleanup
        del x, y
        
        return True
        
    except Exception as e:
        print(f"  ✗ MPS test failed: {e}")
        return False


def _print_acceleration_summary(torch, cuda_available: bool, mps_available: bool) -> None:
    """
    Print summary of acceleration availability.
    
    Args:
        torch: PyTorch module
        cuda_available: Whether CUDA is available and working
        mps_available: Whether MPS is available and working
    """
    print("\nAcceleration Summary:")
    
    if cuda_available:
        device_count = torch.cuda.device_count()
        print(f"  ✓ CUDA acceleration is available and working ({device_count} device(s))")
        print(f"  Recommended device: cuda:0")
    elif mps_available:
        print("  ✓ MPS acceleration is available and working")
        print("  Recommended device: mps")
    else:
        print("  ℹ No hardware acceleration available, using CPU only")
        print("  Recommended device: cpu")
        
        # Test CPU functionality
        _test_cpu_functionality(torch)


def _test_cpu_functionality(torch) -> None:
    """
    Test CPU processing functionality.
    
    Args:
        torch: PyTorch module
    """
    try:
        x = torch.tensor([1.0, 2.0, 3.0])
        y = x * 2
        result = y.numpy()
        
        # Verify results
        expected = [2.0, 4.0, 6.0]
        if not all(abs(a - b) < 1e-6 for a, b in zip(result, expected)):
            print(f"  ✗ CPU computation error: expected {expected}, got {result.tolist()}")
            return
        
        print(f"  CPU test result: {result.tolist()}")
        print("  ✓ CPU processing is working correctly!")
        
        # Cleanup
        del x, y
        
    except Exception as e:
        print(f"  ✗ CPU test failed: {e}")


def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments.
    
    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="Check PyTorch installation and hardware acceleration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python check_pytorch_hardware_acceleration.py                    # Basic check
  python check_pytorch_hardware_acceleration.py --verbose          # Show all devices
  python check_pytorch_hardware_acceleration.py --device 1         # Test specific GPU
  python check_pytorch_hardware_acceleration.py --verbose --device 1  # Detailed info for specific GPU
        """
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed information including all GPU devices"
    )
    
    parser.add_argument(
        "--device", "-d",
        type=int,
        default=0,
        metavar="ID",
        help="Specific CUDA device ID to test (default: 0)"
    )
    
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    check_pytorch(verbose=args.verbose, device_id=args.device)