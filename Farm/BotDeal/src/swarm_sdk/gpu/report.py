"""Host GPU acceleration inventory for this Mac (Radeon Pro 5300M + MoltenVK).

Your discrete AMD GPU *does* accelerate compute through:

- **Vulkan via MoltenVK** → Metal (llama.cpp / GGML Vulkan, Kompute, etc.)
- **OpenCL.framework** (legacy Apple/AMD path; still present on this host)
- **Metal** (native)

Swarm can now use these backends via:

- `LlamaCppEmbedder` with a Vulkan/MoltenVK-capable `llama-cpp-python` build.
- OpenCL-backed batch dot/cosine/normalize/top-k in `swarm_sdk.gpu`.
- `OpenClVecStore` brute-force vector search.

See ``~/Documentos/Molten.md`` for Vulkan0 = AMD Radeon Pro 5300M setup.
"""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

from swarm_sdk.gpu.opencl_math import opencl_status


def _exists(*paths: str) -> bool:
    return any(Path(p).exists() for p in paths)


def _moltenvk_status() -> str:
    icd = os.environ.get("VK_ICD_FILENAMES", "")
    if icd and Path(icd.split(":")[0]).is_file():
        return "icd-env"
    if _exists(
        "/usr/local/etc/vulkan/icd.d/MoltenVK_icd.json",
        "/opt/homebrew/etc/vulkan/icd.d/MoltenVK_icd.json",
    ):
        return "icd-present"
    if _exists(
        "/usr/local/opt/molten-vk/lib/libMoltenVK.dylib",
        "/usr/local/lib/libMoltenVK.dylib",
        "/opt/homebrew/opt/molten-vk/lib/libMoltenVK.dylib",
    ):
        return "lib-present"
    return "not-found"


def _opencl_status() -> str:
    # On modern macOS the OpenCL binary may be a dyld shared-cache stub;
    # the framework directory is enough to know Apple/AMD OpenCL is available.
    framework = Path("/System/Library/Frameworks/OpenCL.framework")
    if framework.is_dir():
        return "framework-present"
    if _exists(
        "/System/Library/Frameworks/OpenCL.framework/OpenCL",
        "/System/Library/Frameworks/OpenCL.framework/Versions/Current/OpenCL",
    ):
        return "framework-present"
    return "not-found"


def _faiss_gpu_status() -> str:
    import importlib

    try:
        faiss = importlib.import_module("faiss")
    except ImportError:
        return "faiss-not-installed"
    if hasattr(faiss, "StandardGpuResources") and hasattr(faiss, "index_cpu_to_gpu"):
        return "cuda-api-present"
    return "cpu-only-build"


def _llama_cpp_status() -> dict[str, str]:
    import importlib

    try:
        llama_cpp = importlib.import_module("llama_cpp")
    except ImportError:
        return {"installed": "false", "vulkan": "unknown"}
    try:
        build_info = llama_cpp.llama_get_device_info()
    except AttributeError:
        build_info = {}
    has_vulkan = bool(getattr(llama_cpp, "LLAMA_VULKAN", False))
    if not has_vulkan and isinstance(build_info, dict):
        has_vulkan = "vulkan" in str(build_info).lower()
    return {
        "installed": "true",
        "vulkan": str(has_vulkan).lower(),
        "version": getattr(llama_cpp, "__version__", "unknown"),
    }


def acceleration_report() -> dict[str, str]:
    """Probe host GPU stack and map it to Swarm embedding / index backends."""
    is_darwin = platform.system() == "Darwin"
    is_x86 = platform.machine() in {"x86_64", "i386"}

    cl_status = opencl_status()
    llama_status = _llama_cpp_status()
    moltenvk = _moltenvk_status()
    vulkan_ok = moltenvk != "not-found"
    llama_vulkan = llama_status["vulkan"] == "true"
    cl_ok = cl_status["available"] == "true"
    return {
        "host": f"{platform.system()}-{platform.machine()}",
        "gpu_profile": "amd-radeon-pro-5300m+intel-uhd-630" if is_darwin and is_x86 else "unknown",
        # Host compute you already use for LLMs / shaders
        "moltenvk": moltenvk,
        "vulkan_compute": "via-moltenvk-for-ggml-llama" if vulkan_ok else "unavailable",
        "opencl_framework": _opencl_status(),
        "opencl_compute": cl_status["available"],
        "opencl_device": cl_status["device"],
        "metal": "supported" if is_darwin else "n/a",
        # Swarm embedding / retrieval backends
        "embed": "llama-cpp-vulkan" if llama_vulkan else "fastembed-onnx-int8-cpu",
        "llama_cpp": llama_status["installed"],
        "llama_cpp_vulkan": llama_status["vulkan"],
        "sqlite_vec": "int8",
        "faiss_gpu": _faiss_gpu_status(),
        "qdrant_quantization": "scalar-int8",
        "qdrant_gpu": "cuda-server-only",
        "swarm_embed_on_radeon": "llama-cpp-vulkan" if llama_vulkan else "no-ort-ep-use-cpu",
        "swarm_index_on_radeon": "opencl-or-cpu" if cl_ok else "cpu-faiss-or-sqlite-vec",
        "note": (
            "Radeon 5300M accelerates Vulkan/MoltenVK (llama.cpp embeddings) and OpenCL "
            "(Swarm math + OpenClVecStore). Enable with embed_backend=llama-cpp and "
            "memory_backend=opencl."
        ),
    }


def print_report() -> None:
    """Print the GPU and environment capability report."""
    for key, value in acceleration_report().items():
        print(f"{key}: {value}")
    if shutil.which("vulkaninfo"):
        print("tip: vulkaninfo --summary  # expect AMD Radeon Pro 5300M as Vulkan0")


if __name__ == "__main__":
    print_report()


__all__ = [
    "acceleration_report",
    "print_report",
]
