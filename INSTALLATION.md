# Installation Guide

This guide provides instructions for setting up the Clinical Guidelines PDF to Markdown Conversion and Chunking Pipeline with either CPU or GPU acceleration.

## Prerequisites

- Python 3.8 or higher
- pip (Python package installer)
- For GPU acceleration: NVIDIA GPU with CUDA support or Apple Silicon for MPS

## Basic Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/shubh2016shiv/clinical-guideline-pdf2md-chunking-pipeline.git
   cd clinical-guideline-pdf2md-chunking-pipeline
   ```

2. Create and activate a virtual environment (recommended):
   ```bash
   # Windows
   python -m venv .venv
   .\.venv\Scripts\activate

   # macOS/Linux
   python -m venv .venv
   source .venv/bin/activate
   ```

3. Install the base requirements:
   ```bash
   pip install -r requirements.txt
   ```

## PyTorch Installation Options

The pipeline uses PyTorch and Torchvision for hardware acceleration and image processing. Choose the appropriate installation method based on your hardware:

### Option 1: CPU-only (Default)

For systems without a compatible GPU or when GPU acceleration is not needed:

```bash
pip install torch torchvision
```

### Option 2: NVIDIA GPU with CUDA

For systems with NVIDIA GPUs, install PyTorch and Torchvision with CUDA support. Choose the appropriate CUDA version based on your NVIDIA drivers:

```bash
# For CUDA 12.1
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# For CUDA 11.8
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# For CUDA 11.7
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu117
```

To check your CUDA version:
```bash
nvidia-smi
```

### Option 3: Apple Silicon (M1/M2/M3)

For Apple Silicon Macs, PyTorch can use Metal Performance Shaders (MPS) for acceleration:

```bash
pip install torch torchvision
```

The default PyTorch installation on macOS includes MPS support.

## Verifying Installation

To verify that PyTorch and Torchvision are correctly installed with the appropriate hardware acceleration:

```bash
python -c "import torch, torchvision; print(f'PyTorch version: {torch.__version__}'); print(f'Torchvision version: {torchvision.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'MPS available: {torch.backends.mps.is_available() if hasattr(torch.backends, \"mps\") else False}')"
```

Or use the provided check script for detailed information:

```bash
python check_pytorch_hardware_acceleration.py
```

## Testing GPU Acceleration

To test that the GPU acceleration is properly configured:

```bash
python gpu_diagnostics.py
```

This will run a comprehensive test of the GPU utilities and verify that hardware acceleration is properly detected and configured.

## Troubleshooting

### CUDA Issues

If you encounter CUDA-related errors:

1. Ensure your NVIDIA drivers are up to date
2. Verify that the CUDA version you installed matches your driver's supported CUDA version
3. Try setting the environment variable: `PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512`

### CPU Fallback

If you want to force CPU usage regardless of GPU availability:

```bash
# Windows
set FORCE_CPU=true

# macOS/Linux
export FORCE_CPU=true
```

Then run your processing script.

## Additional Notes

- The pipeline will automatically detect the best available hardware (CUDA GPU, Apple MPS, or CPU)
- On Windows/Linux systems with NVIDIA GPUs, CUDA will be used if available
- On Apple Silicon Macs, MPS will be used if available
- If no compatible GPU is detected, the system will fall back to CPU processing
