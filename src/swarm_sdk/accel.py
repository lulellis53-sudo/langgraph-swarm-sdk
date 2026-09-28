"""What this machine can actually accelerate.

FAISS GPU and Qdrant GPU builds talk to CUDA. MoltenVK is Vulkan-on-Metal.
Neither ONNX Runtime, FAISS, nor the local Qdrant client uses OpenCL on a
Radeon Pro 5300, so embeddings stay on CPU int8 (FastEmbed ONNX + sqlite-vec).
"""

from __future__ import annotations


def acceleration_report() -> dict[str, str]:
    faiss_gpu = "unavailable"
    try:
        import faiss

        if hasattr(faiss, "StandardGpuResources") and hasattr(faiss, "index_cpu_to_gpu"):
            faiss_gpu = "cuda"
    except ImportError:
        faiss_gpu = "faiss-not-installed"

    return {
        "embed": "fastembed-onnx-int8-cpu",
        "sqlite_vec": "int8",
        "faiss_gpu": faiss_gpu,
        "qdrant_quantization": "scalar-int8",
        "qdrant_gpu": "cuda-server-only",
        "radeon_5300": "cpu-fallback",
        "moltenvk": "not-an-embedding-backend",
        "opencl": "unused",
    }
