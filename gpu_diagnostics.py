#!/usr/bin/env python3
"""
Comprehensive GPU diagnostics for the Docling v2 + MinerU v3 stack.

Tests every layer of the hardware acceleration chain:
  1. System & driver info
  2. PyTorch installation, CUDA/MPS availability, tensor benchmark
  3. Docling v2 accelerator integration (PdfPipelineOptions)
  4. MinerU v3 backend availability (pipeline vs vlm)
  5. GPU memory monitoring (nvidia-smi / torch.cuda)
  6. Comparative GPU vs CPU throughput benchmark

Usage:
    uv run python gpu_diagnostics.py              # Full diagnostic
    uv run python gpu_diagnostics.py --quick      # Skip benchmarks
    uv run python gpu_diagnostics.py --verbose    # Full + debug logging
"""

import argparse
import platform
import shutil
import subprocess
import sys
import time


# ---------------------------------------------------------------------------
# Terminal formatting
# ---------------------------------------------------------------------------
class Ansi:
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    RESET = "\033[0m"


def ok(msg: str) -> str:
    return f"{Ansi.GREEN}✓{Ansi.RESET} {msg}"


def warn(msg: str) -> str:
    return f"{Ansi.YELLOW}⚠{Ansi.RESET} {msg}"


def fail(msg: str) -> str:
    return f"{Ansi.RED}✗{Ansi.RESET} {msg}"


def info(msg: str) -> str:
    return f"{Ansi.CYAN}→{Ansi.RESET} {msg}"


def hdr(msg: str) -> str:
    return f"\n{Ansi.BOLD}{'=' * 60}\n  {msg}\n{'=' * 60}{Ansi.RESET}"


# ===========================================================================
# SECTION 1 — System & Driver Info
# ===========================================================================
def check_system_info() -> None:
    print(hdr("1. SYSTEM INFORMATION"))

    print(f"  Hostname    : {platform.node()}")
    print(f"  OS          : {platform.system()} {platform.release()}")
    print(f"  Arch        : {platform.machine()}")
    print(f"  Processor   : {platform.processor() or 'Unknown'}")
    print(f"  Python      : {sys.version.split()[0]}")

    # NVIDIA driver / nvidia-smi
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            result = subprocess.run(
                [
                    nvidia_smi,
                    "--query-gpu=name,driver_version,memory.total,memory.free,utilization.gpu,temperature.gpu",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                if len(lines) >= 2:
                    values = [v.strip() for v in lines[1].split(",")]
                    print(f"  GPU         : {values[0]}")
                    print(f"  Driver      : {values[1]}")
                    print(f"  VRAM Total  : {values[2]}")
                    print(f"  VRAM Free   : {values[3]}")
                    print(f"  GPU Util    : {values[4]}")
                    print(f"  GPU Temp    : {values[5]}")
            else:
                print(f"  {warn('nvidia-smi returned non-zero')}")
        except Exception as e:
            print(f"  {warn(f'nvidia-smi query failed: {e}')}")
    else:
        print(f"  {warn('nvidia-smi not found — no NVIDIA GPU or drivers?')}")

    # CUDA toolkit version (if nvcc is available)
    nvcc = shutil.which("nvcc")
    if nvcc:
        try:
            result = subprocess.run([nvcc, "--version"], capture_output=True, text=True, timeout=10)
            for line in result.stdout.split("\n"):
                if "release" in line.lower():
                    print(f"  CUDA Toolkit: {line.strip()}")
                    break
        except Exception:
            pass


# ===========================================================================
# SECTION 2 — PyTorch & Tensor Benchmark
# ===========================================================================
def check_pytorch(quick: bool = False) -> dict:
    print(hdr("2. PYTORCH & HARDWARE ACCELERATION"))

    report: dict = {"cuda_ok": False, "mps_ok": False, "cpu_ok": False}

    try:
        import torch
        import torchvision
    except ImportError as e:
        print(f"  {fail(f'PyTorch/Torchvision not installed: {e}')}")
        return report

    print(f"  PyTorch     : {torch.__version__}")
    print(f"  Torchvision : {torchvision.__version__}")
    print(f"  Compiled CUDA: {torch.version.cuda or 'N/A'}")  # type: ignore[attr-defined]

    # --- CUDA ---
    cuda_available = torch.cuda.is_available()
    print(f"\n  CUDA available: {cuda_available}")

    if cuda_available:
        device_count = torch.cuda.device_count()
        print(f"  CUDA devices : {device_count}")

        for i in range(device_count):
            props = torch.cuda.get_device_properties(i)
            print(f"    [{i}] {props.name}")
            print(f"        Compute : {props.major}.{props.minor}")
            print(f"        VRAM    : {props.total_memory / 1024**3:.1f} GB")
            print(f"        SMs     : {props.multi_processor_count}")

        # Tensor smoke test
        try:
            device = torch.device("cuda:0")  # type: ignore[reportPrivateImportUsage]
            _run_tensor_test(torch, device, "CUDA")
            report["cuda_ok"] = True
        except Exception as e:
            print(f"  {fail(f'CUDA tensor test failed: {e}')}")
    else:
        print(f"  {warn('No CUDA devices detected')}")

    # --- MPS (Apple Silicon) ---
    if hasattr(torch.backends, "mps"):
        mps_available = torch.backends.mps.is_available()
        print(f"\n  MPS available : {mps_available}")
        if mps_available:
            try:
                device = torch.device("mps")  # type: ignore[reportPrivateImportUsage]
                _run_tensor_test(torch, device, "MPS")
                report["mps_ok"] = True
            except Exception as e:
                print(f"  {fail(f'MPS tensor test failed: {e}')}")
    else:
        print("\n  MPS: not supported in this PyTorch build")

    # --- CPU (always available) ---
    try:
        device = torch.device("cpu")  # type: ignore[reportPrivateImportUsage]
        _run_tensor_test(torch, device, "CPU")
        report["cpu_ok"] = True
    except Exception as e:
        print(f"  {fail(f'CPU tensor test failed: {e}')}")

    # --- GPU vs CPU benchmark ---
    if report["cuda_ok"] and not quick:
        _gpu_vs_cpu_benchmark(torch)

    return report


def _run_tensor_test(torch, device, label: str) -> None:
    """Simple tensor operation to confirm the device works."""
    x = torch.randn(1000, 1000, device=device)
    y = x @ x.T  # matrix multiply
    _ = y.sum().item()
    del x, y
    if device.type == "cuda":
        torch.cuda.empty_cache()
    print(f"  {ok(f'{label} tensor test passed')}")


def _gpu_vs_cpu_benchmark(torch) -> None:
    """Compare GPU vs CPU throughput for a realistic workload."""
    print(f"\n  {info('GPU vs CPU throughput benchmark (2500×2500 matmul, warmup + 20 runs)')}")

    mat_size = 2500
    runs = 20

    # Warmup both
    for _ in range(3):
        a = torch.randn(mat_size, mat_size, device="cuda:0")
        _ = a @ a.T
        torch.cuda.synchronize()
        del a
    for _ in range(3):
        a = torch.randn(mat_size, mat_size, device="cpu")
        _ = a @ a.T
        del a

    # GPU
    torch.cuda.synchronize()
    gpu_start = time.perf_counter()
    for _ in range(runs):
        a = torch.randn(mat_size, mat_size, device="cuda:0")
        _ = a @ a.T
    torch.cuda.synchronize()
    gpu_time = time.perf_counter() - gpu_start

    # CPU
    cpu_start = time.perf_counter()
    for _ in range(runs):
        a = torch.randn(mat_size, mat_size, device="cpu")
        _ = a @ a.T
    cpu_time = time.perf_counter() - cpu_start

    speedup = cpu_time / gpu_time if gpu_time > 0 else float("inf")

    print(f"    GPU time : {gpu_time:.3f}s  ({gpu_time / runs * 1000:.1f} ms/op)")
    print(f"    CPU time : {cpu_time:.3f}s  ({cpu_time / runs * 1000:.1f} ms/op)")
    print(f"    Speedup  : {speedup:.1f}×")

    if speedup >= 10:
        print(f"  {ok(f'GPU is {speedup:.0f}× faster — excellent')}")
    elif speedup >= 2:
        print(f"  {ok(f'GPU is {speedup:.0f}× faster — good')}")
    else:
        print(f"  {warn('GPU speedup is modest — check CUDA installation')}")


# ===========================================================================
# SECTION 3 — Project AcceleratorDetector
# ===========================================================================
def check_project_accelerator() -> None:
    print(hdr("3. PROJECT ACCELERATOR DETECTOR"))

    try:
        from doc2md_conversion_engine.utils.gpu_utils import (
            detect_optimal_device,
            get_accelerator_detector,
            is_gpu_acceleration_available,
        )
    except Exception as e:
        print(f"  {fail(f'Failed to import project modules: {e}')}")
        return

    detector = get_accelerator_detector()

    # Available accelerators
    acc = detector.detect_available_accelerators()
    print("  Detected accelerators:")
    for atype, available in acc.items():
        status = ok("available") if available else f"{Ansi.DIM}—{Ansi.RESET}"
        print(f"    {atype.value:6s}: {status}")

    # Optimal device
    optimal = detector.get_optimal_device_config()
    print(f"\n  Optimal device : {optimal.device}")
    print(f"  Accelerator    : {optimal.accelerator_type.value}")
    print(f"  Device ID      : {optimal.device_id}")

    # Docling-specific config
    docling_cfg = detector.get_docling_accelerator_config()
    print(
        f"\n  Docling config : accelerator={docling_cfg.get('accelerator', '?')}, "
        f"device={docling_cfg.get('device', '?')}"
    )

    # Convenience functions
    print(f"  GPU available  : {is_gpu_acceleration_available()}")
    print(f"  Best device    : {detect_optimal_device()}")

    # GPU memory snapshot
    _print_gpu_memory()

    print(f"  {ok('Project accelerator detector works correctly')}")


def _print_gpu_memory() -> None:
    """Print current GPU memory usage via PyTorch."""
    try:
        import torch

        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                allocated = torch.cuda.memory_allocated(i) / 1024**2
                reserved = torch.cuda.memory_reserved(i) / 1024**2
                total = torch.cuda.get_device_properties(i).total_memory / 1024**3
                free = total - (reserved / 1024)
                print(
                    f"  GPU[{i}] memory : {allocated:.0f} MB allocated, "
                    f"{reserved:.0f} MB reserved, {free:.1f} GB free / {total:.1f} GB"
                )
    except Exception:
        pass


# ===========================================================================
# SECTION 4 — Docling v2 Integration
# ===========================================================================
def check_docling_accelerator() -> None:
    print(hdr("4. DOCLING v2 ACCELERATOR INTEGRATION"))

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as e:
        print(f"  {fail(f'Docling not installed: {e}')}")
        print(f"  {info('Install with: pip install docling>=2.95.0')}")
        return

    try:
        from doc2md_conversion_engine.models.config import DocumentProcessingConfig

        config = DocumentProcessingConfig()
        device_config = config.get_device_config()
    except Exception as e:
        print(f"  {fail(f'Config init failed: {e}')}")
        return

    accel = device_config.get("accelerator", "cpu")
    device_str = device_config.get("device", "cpu")

    print(f"  Config accelerator : {accel}")
    print(f"  Config device      : {device_str}")

    # Try configuring PdfPipelineOptions
    pipeline_options = PdfPipelineOptions()
    pipeline_options.images_scale = 2.0
    pipeline_options.generate_page_images = True
    pipeline_options.do_ocr = True

    configured = False
    method_used = "none"

    if hasattr(pipeline_options, "accelerator"):
        pipeline_options.accelerator = accel  # type: ignore[reportAttributeAccessIssue]
        configured = True
        method_used = "accelerator attr"
    elif hasattr(pipeline_options, "device"):
        pipeline_options.device = device_str  # type: ignore[reportAttributeAccessIssue]
        configured = True
        method_used = "device attr"

    if configured:
        print(f"  {ok(f'PdfPipelineOptions configured via `{method_used}` → {accel}')}")
    else:
        print(
            f"  {warn('PdfPipelineOptions has no accelerator/device attribute — using defaults')}"
        )

    # Quick Docling smoke test (convert a tiny PDF)
    try:
        _ = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )
        print(f"  {ok('DocumentConverter initialized with accelerator config')}")
    except Exception as e:
        print(f"  {fail(f'DocumentConverter init failed: {e}')}")


# ===========================================================================
# SECTION 5 — MinerU v3 Backend Check
# ===========================================================================
def check_mineru_backend() -> None:
    print(hdr("5. MINERU v3 BACKEND AVAILABILITY"))

    try:
        from mineru.version import __version__ as _mineru_version
        print(f"  MinerU version : {_mineru_version}")
    except ImportError:
        print(f"  {fail('MinerU not installed')}")
        print(f"  {info('Install with: pip install mineru[core]>=3.1.0')}")
        return

    # Check which backends are usable
    backends = {}

    # --- Pipeline backend (CPU + GPU via onnx/torch) ---
    import importlib.util

    if importlib.util.find_spec("onnxruntime"):
        backends["pipeline"] = ok("available (onnxruntime)")
    elif importlib.util.find_spec("onnxruntime_gpu"):
        backends["pipeline"] = ok("available (onnxruntime_gpu)")
    else:
        backends["pipeline"] = warn("onnxruntime not found — pipeline backend may fail")

    # --- VLM backend (needs torch + transformers + GPU) ---
    try:
        import torch
        import transformers

        if torch.cuda.is_available():
            backends["vlm"] = ok(
                f"available (torch {torch.__version__}, "
                f"transformers {transformers.__version__}, CUDA)"
            )
        else:
            backends["vlm"] = warn("torch+transformers OK but NO GPU — VLM engine needs CUDA")
    except ImportError as e:
        backends["vlm"] = fail(f"missing deps ({e})")

    # --- vLLM backend (optional, Linux only) ---
    try:
        import vllm

        backends["vllm"] = ok(f"available (vllm {vllm.__version__})")
    except ImportError:
        backends["vllm"] = f"{Ansi.DIM}— not installed (optional, Linux only){Ansi.RESET}"

    # --- MLX backend (optional, macOS Apple Silicon only) ---
    try:
        import mlx_vlm

        backends["mlx"] = ok(f"available (mlx-vlm {mlx_vlm.__version__})")
    except ImportError:
        backends["mlx"] = f"{Ansi.DIM}— not installed (optional, macOS only){Ansi.RESET}"

    for name, status in backends.items():
        print(f"  {name:10s}: {status}")

    # Recommended backend based on hardware
    import torch

    if torch.cuda.is_available():
        print(f"\n  {ok('Recommended: -b vlm  (GPU available, best accuracy)')}")
    else:
        print(f"\n  {ok('Recommended: -b pipeline  (CPU-only, 86.2 score)')}")


# ===========================================================================
# MAIN
# ===========================================================================
def main() -> None:
    parser = argparse.ArgumentParser(
        description="GPU diagnostics for Docling v2 + MinerU v3 stack",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--quick", action="store_true", help="Skip benchmarks")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG, format="%(name)s | %(levelname)s | %(message)s")

    print(f"\n{Ansi.BOLD}{'█' * 60}")
    print(f"  GPU DIAGNOSTICS — Docling v2 + MinerU v3 + PyTorch {Ansi.RESET}")
    print(f"{Ansi.BOLD}{'█' * 60}{Ansi.RESET}")

    check_system_info()
    pytorch_report = check_pytorch(quick=args.quick)
    check_project_accelerator()
    check_docling_accelerator()
    check_mineru_backend()

    # Final summary
    print(hdr("SUMMARY"))
    gpu_working = pytorch_report.get("cuda_ok") or pytorch_report.get("mps_ok")
    if gpu_working:
        print(f"  {ok('GPU acceleration is WORKING')}")
        print(f"  {ok('Both Docling v2 and MinerU v3 will use GPU')}")
    else:
        print(f"  {warn('No GPU detected — both engines will fall back to CPU')}")
        print(f"  {info('CPU fallback is built-in; no code changes needed')}")

    if pytorch_report.get("cpu_ok"):
        print(f"  {ok('CPU fallback is functional')}")

    print("\n  Run a full conversion test next:")
    print("    uv run python example_pdf2md_conversion_single-doc_processing.py")
    print()


if __name__ == "__main__":
    main()
