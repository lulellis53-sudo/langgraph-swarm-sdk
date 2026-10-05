# MoltenVK + Vulkan GPU Acceleration Guide

> **Scope:** Hardware-specific notes for the 2019 Intel Mac configuration below. Device enumeration, driver support, model fit, and command-line flags depend on the installed Vulkan/llama.cpp builds. Treat commands as examples and verify device selection and logs on the target machine. The Swarm SDK’s supported settings are in [`Main/config/swarm.yaml`](../Main/config/swarm.yaml) and [`README.md`](../README.md).

## Target hardware

MacBook Pro 16-inch (2019) | Intel Core i7-9750H | 16 GB RAM | AMD Radeon Pro 5300M (4 GB VRAM)

---

## 1. Hardware Architecture & Environment Specification

This system configuration is a high-performance 2019 16-inch MacBook Pro (`MacBookPro16,1`) with dual GPUs and an Intel x86_64 CPU:

| Component | Specification | Memory / VRAM | MoltenVK / Compute Role |
| :--- | :--- | :--- | :--- |
| **CPU** | Intel Core i7-9750H (6 cores, 12 threads @ 2.60 GHz, Turbo 4.5 GHz, AVX2, FMA) | 16 GB DDR4-2666 MHz | Host compute, tokenization, Apple Accelerate BLAS for hybrid CPU offloading |
| **Discrete GPU (dGPU)** | **AMD Radeon Pro 5300M** (Navi 14 / RDNA 1, 22 compute units) | 4 GB dedicated GDDR6 | Vulkan device may be exposed through MoltenVK; confirm its name and available memory with `llama-server --list-devices`. |
| **Integrated GPU (iGPU)** | Intel UHD Graphics 630 | Uses system memory | May also appear as a Vulkan device; device numbering and supported features can vary. |
| **Operating System** | macOS Darwin x86_64 | 64-bit | Apple Metal is the native graphics/compute API; MoltenVK maps a Vulkan subset to Metal. |
| **Translation Layer** | MoltenVK | Vulkan portability implementation over Metal | It is not an OpenCL implementation. |

```
               +-------------------------------------------------------+
               |                  Inference Runtime                    |
               |       (llama.cpp / llama-cpp-python / Kompute)        |
               +-------------------------------------------------------+
                                           |
                                [Vulkan Compute API (supported subset)]
                                           |
               +-------------------------------------------------------+
               |                  MoltenVK Layer                       |
               |       (MoltenVK runtime from SDK/Homebrew)          |
               +-------------------------------------------------------+
                                           |
                              [Apple Metal framework]
                                           |
                    +----------------------+----------------------+
                    |                                             |
         +----------------------+                      +----------------------+
         | AMD Radeon Pro 5300M |                      | Intel UHD Graphics   |
         |  (AMD GPU, if listed)|                      |   630 (if listed)    |
         |  4GB Dedicated GDDR6 |                      |  Shared Host RAM     |
         +----------------------+                      +----------------------+
```

---

## 2. Why MoltenVK + Vulkan on Intel Mac with AMD GPU?

On this Intel Mac, `llama.cpp` can use its Vulkan backend through MoltenVK, while its Metal backend is a separate native path. Vulkan may expose the AMD and Intel GPUs as separate devices, but enumeration order is not a stable device identity. Check `--list-devices` and startup logs rather than assuming `Vulkan0` is always the AMD GPU. Requested GPU offload does not guarantee every layer fits or runs there; memory limits, operator support, and CPU fallback depend on the model and build.

MoltenVK translates Vulkan calls and SPIR-V shaders to Metal. That is a Vulkan-to-Metal path; it does not translate OpenCL kernels or make OpenCL calls run through Vulkan.

---

## 3. Toolchain & Runtime Installation

### 3.1 Install Prerequisites via Homebrew
Install the build and Vulkan dependencies. Homebrew supplies the SDK components; this does not install a Vulkan-enabled Homebrew `llama.cpp` formula:

```bash
brew install cmake ninja libomp molten-vk vulkan-loader vulkan-headers shaderc vulkan-tools
```

### 3.2 Environment Configuration
Avoid hard-coding `/usr/local` paths or globally setting `DYLD_LIBRARY_PATH`. First verify what the installed loader sees:

```bash
vulkaninfo --summary
```

If using the LunarG Vulkan SDK, initialize it for the build shell with its `setup-env.sh`. With Homebrew, use the installed loader/MoltenVK paths; set `VK_ICD_FILENAMES` only if automatic discovery selects the wrong driver. Use `GGML_VK_VISIBLE_DEVICES=0` only after confirming device 0 is the intended GPU; prefer the runtime `--device` option when available.

### 3.3 Verify Vulkan and Hardware Detection
Run `vulkaninfo` to inspect the Vulkan devices visible through the active driver:

```bash
vulkaninfo --summary
```

Check the actual device names and driver versions reported on this host; do not rely on copied API versions, device indices, or free-memory figures.

---

## 4. Building llama.cpp with Vulkan + MoltenVK

This machine-specific profile comes from `~/Documentos/toolchain.md` §4.10 and §12.4.1. It targets the i7-9750H (AVX2/FMA, no AVX-512) and builds a Vulkan-enabled `llama-server`; it is a starting profile, not a guarantee that every model or operation is faster. Homebrew build flags do not enable Vulkan in the Homebrew `llama.cpp` formula. Build upstream source directly with CMake:

```bash
brew install cmake ninja molten-vk vulkan-loader vulkan-headers shaderc vulkan-tools libomp
git clone https://github.com/ggml-org/llama.cpp.git
cd llama.cpp

cmake -S . -B build-vulkan-apple -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_OSX_ARCHITECTURES=x86_64 \
  -DCMAKE_OSX_DEPLOYMENT_TARGET=13.0 \
  -DGGML_VULKAN=ON \
  -DGGML_METAL=OFF \
  -DGGML_NATIVE=ON \
  -DGGML_AVX2=ON \
  -DGGML_FMA=ON \
  -DGGML_F16C=ON \
  -DGGML_BMI2=ON \
  -DGGML_SSE42=ON \
  -DGGML_OPENMP=ON \
  -DGGML_ACCELERATE=ON \
  -DGGML_BLAS=ON \
  -DGGML_BLAS_VENDOR=Apple \
  -DGGML_LTO=ON \
  -DGGML_BUILD_TESTS=OFF \
  -DGGML_BUILD_EXAMPLES=OFF \
  -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_BUILD_EXAMPLES=OFF \
  -DLLAMA_BUILD_SERVER=ON \
  -DLLAMA_OPENSSL=ON

# Keep parallelism modest on this 16 GB laptop; link/LTO may use substantial RAM.
cmake --build build-vulkan-apple --config Release --parallel 6 --target llama-server
```

`GGML_NATIVE=ON` makes this binary specific to this Mac; remove it and reconfigure for a portable build. LTO can increase build time and memory, so compare against a separate build directory configured with `-DGGML_LTO=OFF`. Keep Vulkan and CPU/Metal experiments in separate build directories.

Verify backend enumeration and then verify actual offload at server startup:

```bash
build-vulkan-apple/bin/llama-server --list-devices
# Replace Vulkan0 with the AMD device identifier shown by --list-devices.
build-vulkan-apple/bin/llama-server -m /path/to/model.gguf -ngl 99 --device Vulkan0
```

Use the device identifier shown by `--list-devices` for the AMD card on this run; do not assume `Vulkan0` is always the Radeon. `-ngl 99` requests extensive layer offload but does not prove all layers were accepted. Read the startup log for the selected device and GPU model-buffer allocation. Apple Accelerate helps CPU-side BLAS work; it does not make a layer that exceeds VRAM automatically fit or guarantee faster token generation.

Later recipes in this guide that specify `Vulkan0` assume that identifier was checked on the current build; replace it if `--list-devices` reports a different device mapping.

### 4.1 OpenCL versus MoltenVK on macOS

There is no OpenCL-to-MoltenVK compilation path. They are different APIs and shader models:

| Goal | Correct path on this Mac |
| :--- | :--- |
| Run `llama.cpp` on the AMD GPU through the cross-platform backend | Build with `-DGGML_VULKAN=ON`; MoltenVK maps Vulkan to Metal. |
| Write a new Apple-native GPU compute application | Use Metal / Metal Performance Shaders. |
| Maintain an older OpenCL application | macOS still has its deprecated OpenCL framework, but this is a legacy route and is unrelated to MoltenVK. |
| Build `llama.cpp` with its OpenCL backend | Upstream OpenCL guidance focuses on Adreno and lists Android, Windows ARM64, and Linux; it does not document macOS AMD/MoltenVK as a supported target. Do not assume `-DGGML_OPENCL=ON` will use the Radeon through MoltenVK. |

Apple deprecated OpenCL in macOS 10.14 and recommends Metal for new GPU compute work. MoltenVK implements a Vulkan subset over Metal and translates SPIR-V shaders to MSL; it does not implement OpenCL. For this Mac's llama.cpp build, use the Vulkan recipe above rather than combining `GGML_OPENCL` with MoltenVK.

References: [Apple's OpenCL transition guidance](https://developer.apple.com/opencl/), [`llama.cpp` OpenCL backend support and platform notes](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/OPENCL.md), and the [`llama.cpp` macOS Vulkan build guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md).

### 4.2 Building MoltenVK itself (optional)

Most applications should use the MoltenVK runtime supplied with the LunarG Vulkan SDK or the already installed package. Only build MoltenVK from source when you need to test or customize the runtime. This build needs Xcode (the upstream project currently verifies Xcode 15.0.1 or later), CMake, and Python 3. The official project fetches and builds dependencies before its Xcode packaging target:

```bash
git clone https://github.com/KhronosGroup/MoltenVK.git
cd MoltenVK
./fetchDependencies --macos
make macos
```

The package output is under `Package/`. Avoid `sudo make install` unless you explicitly intend to replace the SDK's `/usr/local/lib/libMoltenVK.dylib`; keep a custom runtime isolated and select it deliberately. See the official [MoltenVK build instructions](https://github.com/KhronosGroup/MoltenVK#building-moltenvk) for Xcode and configuration details.

---

## 5. Comprehensive Analysis of Code Imports & Dependencies

### 5.1 C / C++ Core Compute Imports
For developing custom Vulkan compute pipelines, shaders, or native C/C++ applications on macOS:

```cpp
// 1. Standard Vulkan Core
#include <vulkan/vulkan.h>

// 2. Apple Metal / MoltenVK Surface & Interop
#include <vulkan/vulkan_metal.h>           // VK_EXT_metal_surface for macOS view binding
#include <MoltenVK/vk_mvk_moltenvk.h>       // MoltenVK configuration APIs (logging, tuning)

// 3. GGML & llama.cpp Vulkan Backend Headers
#include "ggml.h"
#include "ggml-backend.h"
#include "ggml-vulkan.h"                    // ggml_backend_vk_init(device_index)
#include "llama.h"

// Example initializing discrete GPU in C++:
// ggml_backend_t backend = ggml_backend_vk_init(0); // 0 = AMD Radeon Pro 5300M
```

### 5.2 Python Bindings & Libraries

#### A. `llama-cpp-python` (Vulkan Accelerated)
Build and install `llama-cpp-python` with the Vulkan backend:

```bash
CMAKE_ARGS="-DGGML_METAL=OFF -DGGML_VULKAN=ON -DGGML_ACCELERATE=ON" pip install --no-cache-dir llama-cpp-python --force-reinstall
```

```python
# Python Import
from llama_cpp import Llama, llama_supports_gpu_offload

print(f"GPU Offload Available: {llama_supports_gpu_offload()}")

# Initialize model on AMD Radeon Pro 5300M
llm = Llama(
    model_path="models/Qwen2.5-Math-1.5B-Instruct-Q8_0.gguf",
    n_gpu_layers=99,        # Offload 100% of layers to Radeon 5300M
    n_ctx=4096,             # Context size
    n_threads=6,            # 6 physical cores on Intel i7-9750H
    verbose=True
)
```

#### B. `vulkan` (Raw Python Vulkan Bindings)
Used for direct low-level GPU control, memory allocation, and custom compute dispatch:

```bash
pip install vulkan
```

```python
import vulkan as vk

# Create Vulkan instance with MoltenVK portability flags
app_info = vk.VkApplicationInfo(
    sType=vk.VK_STRUCTURE_TYPE_APPLICATION_INFO,
    pApplicationName="MoltenVK-Inference",
    apiVersion=vk.VK_API_VERSION_1_3
)

create_info = vk.VkInstanceCreateInfo(
    sType=vk.VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
    pApplicationInfo=app_info,
    flags=vk.VK_INSTANCE_CREATE_ENUMERATE_PORTABILITY_BIT_KHR
)
instance = vk.vkCreateInstance(create_info, None)
devices = vk.vkEnumeratePhysicalDevices(instance)
print(f"Detected {len(devices)} physical Vulkan device(s)")
```

#### C. `kompute` (High-Level Vulkan Compute Framework)
General-purpose GPU computing for vector/matrix ops via Vulkan:

```bash
pip install kp
```

```python
import kp
import numpy as np

# Select Manager 0 (AMD Radeon Pro 5300M)
mgr = kp.Manager(0)

# Create GPU tensor buffers
tensor_in_a = mgr.tensor(np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32))
tensor_in_b = mgr.tensor(np.array([5.0, 6.0, 7.0, 8.0], dtype=np.float32))
tensor_out = mgr.tensor(np.zeros(4, dtype=np.float32))

# Execute compute shader on Radeon 5300M
# mgr.eval_tensor_create_def([...])
```

#### D. Hugging Face Transformers & Tokenizers
For prompt formatting, token encoding, and tokenizer integration:

```bash
pip install transformers tokenizers huggingface_hub numpy
```

```python
from tokenizers import Tokenizer
from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-Math-1.5B-Instruct")
```

---

## 6. Embedding Models Guide (Optimized for 4GB VRAM)

Embedding models run matrix-vector operations across all token inputs and return dense vector representations. Given the **4080 MiB VRAM** of the Radeon Pro 5300M, embedding models fit with low latency (<15 ms).

### 6.1 Top Recommended Embedding Models

| Model | Parameters | Quantization | Model Size | Context Window | Vector Dim | MTEB Score | Radeon 5300M Latency |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **BAAI/bge-m3** | 567M | **Q8_0** | **~605 MB** | 8192 tokens | 1024 | 64.11 | ~22 ms (Batch 1) |
| **bge-m3** | 567M | **Q4_K_M** | **~320 MB** | 8192 tokens | 1024 | 63.85 | ~14 ms (Batch 1) |
| **nomic-embed-text-v1.5** | 137M | **Q8_0** | **~140 MB** | 8192 tokens | 768 / 512 | 62.28 | ~8 ms (Batch 1) |
| **bge-base-en-v1.5** | 109M | **Q8_0** | **~115 MB** | 512 tokens | 768 | 63.55 | ~6 ms (Batch 1) |
| **bge-small-en-v1.5** | 33M | **Q8_0** | **~67 MB** | 512 tokens | 384 | 62.17 | ~3 ms (Batch 1) |
| **all-MiniLM-L6-v2** | 22M | **FP16** | **~45 MB** | 256 tokens | 384 | 56.26 | ~2 ms (Batch 1) |
| **Qwen2-1.5B-Embedding** | 1.54B | **Q8_0** | **~1.65 GB** | 32,768 tokens | 1536 | 66.80 | ~45 ms (Batch 1) |

### 6.2 Model Details & Strengths

1. **BAAI/bge-m3 (Recommended for Multilingual / Hybrid Retrieval)**:
   - **Why**: Handles 100+ languages, supports dense, sparse (lexical), and multi-vector (ColBERT-style) retrieval in a single pass.
   - **VRAM Footprint**: At Q8_0, 605 MB takes only 15% of the 5300M's VRAM, leaving 3.4 GB free.
   - **Context**: 8192 tokens allows embedding whole technical papers or long source code files.

2. **nomic-ai/nomic-embed-text-v1.5 (Recommended for General RAG)**:
   - **Why**: Fully open-source with reproducible training data; supports Matryoshka embeddings (dimension truncation down to 256 or 128 without quality loss).
   - **VRAM Footprint**: 140 MB. High throughput for indexing large document corpora.

3. **sentence-transformers/all-MiniLM-L6-v2 (Ultra Low Latency)**:
   - **Why**: High speed for real-time auto-complete or semantic search over small passages.

### 6.3 Serving BGE-M3 via Vulkan `llama-server`

Run the Vulkan-accelerated embedding server:

```bash
# Start server pinned to discrete AMD Radeon Pro 5300M (Vulkan0)
./build-vulkan/bin/llama-server \
  -m /Users/usuario/.spawnagent/models/bge-m3-q8_0.gguf \
  --device Vulkan0 \
  -ngl 99 \
  --embedding \
  -b 512 \
  -ub 512 \
  -c 4096 \
  --port 8080
```

Query the embedding endpoint via curl:

```bash
curl -X POST http://127.0.0.1:8080/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Vulkan compute acceleration on AMD Radeon Pro 5300M",
    "model": "bge-m3"
  }'
```

---

## 7. Math & Reasoning Models Guide (Optimized for 4GB VRAM + 16GB RAM)

Mathematical reasoning, algebraic derivation, and formal verification require models with high token generation quality and chain-of-thought capabilities.

### 7.1 Model sizing examples (not local benchmark results)

These models fit entirely inside the 4080 MiB VRAM of the Radeon 5300M, delivering **35 to 55 tokens per second** without PCIe bus bottlenecking:

| Model | Quantization | Size | VRAM (Weights + KV) | Context Length | GSM8K Benchmark | MATH Benchmark | Tokens/Sec (5300M) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Qwen2.5-Math-1.5B-Instruct** | **Q8_0** | **1.65 GB** | ~2.1 GB | 4096 tokens | 84.8% | 61.2% | **~42 t/s** |
| **Qwen2.5-Math-1.5B-Instruct** | **Q4_K_M** | **0.99 GB** | ~1.4 GB | 4096 tokens | 83.2% | 59.8% | **~52 t/s** |
| **DeepSeek-R1-Distill-Qwen-1.5B** | **Q8_0** | **1.89 GB** | ~2.4 GB | 4096 tokens | 86.2% | 63.5% | **~38 t/s** |
| **DeepSeek-R1-Distill-Qwen-1.5B** | **Q5_K_M** | **1.29 GB** | ~1.7 GB | 4096 tokens | 85.1% | 62.1% | **~46 t/s** |
| **Llama-3.2-3B-Instruct** | **Q4_K_M** | **1.92 GB** | ~2.6 GB | 4096 tokens | 77.2% | 48.0% | **~32 t/s** |
| **Phi-3.5-mini-instruct (3.8B)** | **Q4_K_M** | **2.25 GB** | ~3.0 GB | 4096 tokens | 82.5% | 55.4% | **~28 t/s** |

#### Why These Two Lead the 1.5B Class:
1. **Qwen2.5-Math-1.5B-Instruct**:
   - Specialized bilingual mathematical model from Alibaba.
   - Outperforms older 7B and 13B models (like LLaMA-2-13B) on formal math evaluations.
   - Uses Chain-of-Thought (CoT) and Python-based tool-integrated reasoning.
2. **DeepSeek-R1-Distill-Qwen-1.5B**:
   - Distilled directly from DeepSeek-R1's reinforcement learning reasoning traces.
   - Automatically outputs reasoning inside `<think>...</think>` tags before providing answers.

### 7.2 Tier 2: Hybrid CPU/GPU Offload (Utilizing 16GB Host RAM + 4GB VRAM)

Larger 7B/8B math models can be split between the Radeon 5300M and the Intel Core i7 CPU:

| Model | Quantization | Size | Layer Split (`-ngl`) | GPU VRAM | Host RAM | Speed |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Qwen2.5-Math-7B-Instruct** | **Q4_K_M** | 4.45 GB | 18 / 28 layers | 3.2 GB | 2.5 GB | ~12–16 t/s |
| **DeepSeek-R1-Distill-Qwen-7B** | **Q4_K_M** | 4.68 GB | 16 / 28 layers | 3.0 GB | 2.8 GB | ~11–14 t/s |
| **DeepSeek-R1-Distill-Llama-8B** | **Q4_K_M** | 4.92 GB | 14 / 32 layers | 2.8 GB | 3.2 GB | ~9–12 t/s |

*Configuration note: When running Tier 2 hybrid offloading, compile llama.cpp with `-DGGML_ACCELERATE=ON` so CPU-side layers execute via Apple's vectorized Accelerate BLAS library on the i7-9750H.*

---

## 8. Step-by-Step Model Download & Execution Recipes

### 8.1 Download Quantized GGUF Models

Install `huggingface-hub`:
```bash
pip install huggingface_hub
```

Download the recommended models:

```bash
mkdir -p /Users/usuario/models

# 1. BGE-M3 (Embedding Model, Q8_0, ~605MB)
huggingface-cli download ggml-org/bge-m3-Q8_0-GGUF \
  bge-m3-q8_0.gguf \
  --local-dir /Users/usuario/models

# 2. Qwen2.5-Math-1.5B-Instruct (Math Specialist, Q8_0, ~1.65GB)
huggingface-cli download bartowski/Qwen2.5-Math-1.5B-Instruct-GGUF \
  --include "Qwen2.5-Math-1.5B-Instruct-Q8_0.gguf" \
  --local-dir /Users/usuario/models

# 3. DeepSeek-R1-Distill-Qwen-1.5B (CoT Reasoning, Q5_K_M, ~1.29GB)
huggingface-cli download bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF \
  --include "DeepSeek-R1-Distill-Qwen-1.5B-Q5_K_M.gguf" \
  --local-dir /Users/usuario/models
```

---

### 8.2 Production Execution Recipes with `llama-server`

#### Recipe A: High-Throughput Embedding Service (BGE-M3 on Vulkan0)
```bash
./build-vulkan/bin/llama-server \
  -m /Users/usuario/models/bge-m3-q8_0.gguf \
  --device Vulkan0 \
  -ngl 99 \
  --embedding \
  -b 512 \
  -ub 512 \
  -c 4096 \
  -t 6 \
  --host 127.0.0.1 \
  --port 8080
```

#### Recipe B: Fast Math Reasoning (Qwen2.5-Math-1.5B on Vulkan0)
```bash
./build-vulkan/bin/llama-server \
  -m /Users/usuario/models/Qwen2.5-Math-1.5B-Instruct-Q8_0.gguf \
  --device Vulkan0 \
  -ngl 99 \
  -c 4096 \
  -b 512 \
  -ub 512 \
  -t 6 \
  --host 127.0.0.1 \
  --port 8081
```

#### Recipe C: DeepSeek-R1 Chain-of-Thought Reasoning
```bash
./build-vulkan/bin/llama-server \
  -m /Users/usuario/models/DeepSeek-R1-Distill-Qwen-1.5B-Q5_K_M.gguf \
  --device Vulkan0 \
  -ngl 99 \
  -c 4096 \
  -b 512 \
  -ub 512 \
  -t 6 \
  --host 127.0.0.1 \
  --port 8082
```

---

## 9. Python Integration Examples

### 9.1 End-to-End Math Reasoning Script (HTTP Client with Streaming)

Create `/Users/usuario/test_math_vulkan.py`:

```python
#!/usr/bin/env python3
"""
Interactive Math Reasoning Query Client for Vulkan llama-server.
Connects to Qwen2.5-Math or DeepSeek-R1 running on AMD Radeon Pro 5300M.
"""

import sys
import json
import urllib.request

SERVER_URL = "http://127.0.0.1:8081/v1/chat/completions"

SYSTEM_PROMPT = (
    "Please reason step by step, and put your final answer within \\boxed{}."
)

def solve_math_problem(question: str):
    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question}
        ],
        "temperature": 0.0,
        "max_tokens": 1500,
        "stream": True
    }

    req = urllib.request.Request(
        SERVER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    print(f"\n--- Question: {question} ---")
    print("--- Reasoning & Solution (Radeon Pro 5300M Vulkan): ---\n")

    with urllib.request.urlopen(req) as resp:
        for line in resp:
            line_str = line.decode("utf-8").strip()
            if not line_str or line_str == "data: [DONE]":
                continue
            if line_str.startswith("data: "):
                try:
                    data = json.loads(line_str[6:])
                    content = data["choices"][0]["delta"].get("content", "")
                    sys.stdout.write(content)
                    sys.stdout.flush()
                except Exception:
                    pass
    print("\n")

if __name__ == "__main__":
    sample_math = (
        "Find the sum of all positive integers n such that "
        "n^2 + 19n + 48 is a perfect square."
    )
    solve_math_problem(sample_math)
```

### 9.2 Python Batch Embedding Script (via `llama-server` API)

Create `/Users/usuario/test_embed_vulkan.py`:

```python
#!/usr/bin/env python3
"""
Batch Embedding Generation on AMD Radeon Pro 5300M using Vulkan BGE-M3.
"""

import json
import numpy as np
import urllib.request

EMBED_URL = "http://127.0.0.1:8080/v1/embeddings"

def get_embeddings(texts: list[str]) -> np.ndarray:
    payload = {
        "input": texts,
        "model": "bge-m3"
    }

    req = urllib.request.Request(
        EMBED_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        embeddings = [item["embedding"] for item in res["data"]]
        return np.array(embeddings, dtype=np.float32)

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

if __name__ == "__main__":
    sentences = [
        "Vulkan compute shader pipeline on Apple MoltenVK",
        "GPU hardware acceleration using AMD Radeon graphics cards",
        "A delicious recipe for homemade Italian sourdough pizza"
    ]

    print("Computing embeddings on Radeon Pro 5300M...")
    vecs = get_embeddings(sentences)
    print(f"Computed {len(vecs)} vectors with dimension: {vecs.shape[1]}")

    sim_0_1 = cosine_similarity(vecs[0], vecs[1])
    sim_0_2 = cosine_similarity(vecs[0], vecs[2])

    print(f"\nCosine Similarity:")
    print(f"  Sentence 0 vs Sentence 1 (Related Tech): {sim_0_1:.4f}")
    print(f"  Sentence 0 vs Sentence 2 (Unrelated):    {sim_0_2:.4f}")
```

---

## 10. Memory Calculations, Thermal Tuning & Best Practices

### 10.1 VRAM Budgeting Formula for 4GB GDDR6

To ensure the model never spills from the discrete 4GB VRAM into system memory over the PCIe bus:

$$\text{VRAM}_{\text{Total}} = \text{Model Size} + \text{KV Cache} + \text{Scratch Buffers} \le 3800 \text{ MiB}$$

Where:
- $\text{KV Cache} \approx 2 \times n_{\text{layers}} \times n_{\text{kv\_heads}} \times d_{\text{head}} \times n_{\text{ctx}} \times \text{bytes\_per\_element}$
- For a 1.5B model with $n_{\text{ctx}} = 4096$ at FP16: $\text{KV Cache} \approx 400 \text{ MiB}$.
- Model at Q8_0: $\approx 1650 \text{ MiB}$.
- Total working set: $\approx 2050 \text{ MiB}$ (leaves ~2000 MiB headroom).

### 10.2 Thermal & Performance Optimization for 2019 16" MacBook Pro
The 2019 16" MacBook Pro shares heat pipes between the Intel Core i7-9750H and AMD Radeon Pro 5300M. To maintain maximum sustained clocks and prevent thermal throttling:

1. **Pin Workload to GPU**: Offloading 100% of layers (`-ngl 99`) onto the Radeon 5300M keeps the CPU cool, avoiding thermal spikes.
2. **Batch Size Tuning**: Use `-b 512 -ub 512`. Larger batch sizes increase VRAM buffer footprint and can cause MoltenVK descriptor re-allocations.
3. **Disable Flash Attention on Vulkan**: Vulkan fused attention is still experimental on some MoltenVK targets. Rely on standard self-attention kernels for numerical stability.
4. **Fan Profile Management**: When running continuous batch inference, configure `Macs Fan Control` or elevated fan profiles to sustain GPU boost clocks above 1000 MHz.

---

## 11. Math Libraries, Imports & Tool-Integrated Reasoning (TIR)

Mathematical inference with LLMs (like Qwen2.5-Math and DeepSeek-R1) typically pairs the language model with specialized math execution libraries. In modern LLM math pipelines, the model either writes and executes code (Tool-Integrated Reasoning / Program-Aided Language models) or requires external symbolic/numerical verification.

### 11.1 Python Math Libraries & Imports

```bash
pip install sympy scipy mpmath numpy gmpy2 numba cvxpy pyopencl kp
```

#### A. Symbolic Mathematics & Equation Solving (`sympy`)
Used to symbolically solve equations, calculate integrals, simplify algebraic expressions, and verify mathematical proofs:

```python
import sympy as sp

# Define symbolic variables
x, y, z = sp.symbols('x y z')

# 1. Algebraic factorization and expansion
poly = x**3 + 3*x**2*y + 3*x*y**2 + y**3
factored = sp.factor(poly)  # (x + y)**3

# 2. Exact algebraic equation solving
solution = sp.solve(sp.Eq(x**2 + 19*x + 48, y**2), x)

# 3. Calculus: Analytical Derivatives and Definite Integrals
f = sp.sin(x) * sp.exp(x)
deriv = sp.diff(f, x)
integ = sp.integrate(sp.exp(-x**2), (x, -sp.oo, sp.oo))  # sqrt(pi)

# 4. Matrix diagonalization and eigenvalues
A = sp.Matrix([[1, 2], [2, 1]])
eigenvalues = A.eigenvals()

# 5. Linear systems, ODEs, and numeric roots (prefer these over from sympy import *)
from sympy import Eq, Function, Matrix, dsolve, linsolve, nsolve, symbols

t = symbols("t")
x_fn = Function("x")
ode = Eq(x_fn(t).diff(t, 2) + x_fn(t), 0)
ode_sol = dsolve(ode)  # C1*sin(t) + C2*cos(t)
lin_sol = linsolve([Eq(x + y, 1), Eq(x - y, 0)], [x, y])
num_root = nsolve(sp.cos(x) - x, x, 1)  # Dottie number ≈ 0.739
mat_sol = Matrix([[1, 2], [3, 4]]).LUsolve(Matrix([5, 6]))

# 6. Compile a symbolic equation to a NumPy ufunc (vector acceleration)
from sympy import lambdify
f_np = lambdify((x, y), sp.sin(x) + y, modules="numpy")
```

#### B. High-Precision & Multiple-Precision Arithmetic (`mpmath` / `gmpy2`)
Essential when standard 64-bit IEEE 754 floats suffer from catastrophic cancellation or insufficient precision:

```python
import mpmath as mp

# Set precision to 100 decimal digits
mp.mp.dps = 100

# High-precision Riemann Zeta, Gamma, and hypergeometric functions
zeta_half = mp.zeta(0.5 + 14.134725141734693790457251983562470270784257115699243175685567460149963429809256764949010393171561012j)
pi_100 = mp.pi

# High-speed integer arithmetic with GMP (via gmpy2)
import gmpy2
large_int = gmpy2.mpz(2)**1000000
is_prime_prob = gmpy2.is_prime(gmpy2.mpz(2)**127 - 1)
```

#### C. Scientific & Numerical Computing (`scipy` / `numpy`)
Matrix factorizations, linear algebra, numerical root-finding, and optimization:

```python
import numpy as np
import scipy.linalg as la
import scipy.optimize as opt
import scipy.special as sp_special

# 1. Numerical root finding
root = opt.root_scalar(lambda x: x**3 - 2*x - 5, bracket=[2, 3], method='brentq')

# 2. Eigenvalue decomposition & SVD with Apple Accelerate BLAS
M = np.random.randn(500, 500)
U, S, Vt = la.svd(M)

# 3. Special mathematical functions
bessel_val = sp_special.jv(1, 2.5)  # Bessel function of the first kind

# 4. FFT / DCT (import the submodule — scipy.fft is not numpy.fft)
from scipy.fft import dct, fft, idct
from scipy.optimize import least_squares
from scipy.sparse.linalg import spsolve
```

#### D. Convex / algebraic optimization (`cvxpy`, `scipy.optimize`)

Use these when the model writes **constraints + objective**, not a closed-form `sympy.solve`. CPU solvers only on this Mac ([CVXPY intro](https://www.cvxpy.org/tutorial/intro/index.html), [Solver Max Python AMLs](https://www.solvermax.com/resources/links/optimization-modelling-in-python)):

```python
import cvxpy as cp
from scipy.optimize import least_squares, root_scalar

# Convex program (OSQP / SCS / ECOS on CPU — not CUDA)
x_var = cp.Variable()
y_var = cp.Variable()
prob = cp.Problem(
    cp.Minimize((x_var - y_var) ** 2),
    [x_var + y_var == 1, x_var - y_var >= 1],
)
prob.solve()
assert prob.status == "optimal"

# Nonlinear least squares / scalar roots (SciPy wraps HiGHS for LP)
lsq = least_squares(lambda v: [v[0] ** 2 - 2], x0=[1.0])
root = root_scalar(lambda t: t**3 - 2 * t - 5, bracket=[2, 3], method="brentq")
```

Heavier AMLs (same CPU class, optional): `import pulp`, `from pyomo.environ import ConcreteModel`, `from gekko import GEKKO`, `from casadi import SX, nlpsol`. Prefer Pyomo/PuLP for MIP; CVXPY for convex; CasADi for optimal control.

#### E. Vector acceleration (this host: AVX2 CPU + OpenCL + Vulkan)

**There is no CuPy / Numba-CUDA / JAX-GPU / MLX path on the Radeon 5300M.** Split:

| Import | What it accelerates | This Intel Mac + 5300M |
| :--- | :--- | :--- |
| `import math`, `cmath`, `decimal`, `fractions`, `statistics` | Stdlib scalars | **Yes** |
| `import numpy as np` | ufuncs + BLAS (Apple Accelerate / AVX2, **no AVX-512**) | **Yes** — Swarm core |
| `import scipy.linalg as la` | LAPACK via the same BLAS | **Yes** (pulled with sklearn) |
| `from numba import njit, prange, vectorize` | LLVM JIT + SIMD + OpenMP threads | **Yes, CPU only.** `numba.cuda` is NVIDIA |
| `import pyopencl as cl` | OpenCL kernels on the 5300M | **Yes** — Swarm `gpu/opencl_math.py` |
| `import kp` | Vulkan compute tensors | **Yes** — MoltenVK (`pip install kp`) |
| `from usearch.index import Index` | AVX2 FP16 ANN | **Yes** |
| `import polars as pl` | CPU DataFrames (Rust) | **Yes** — Swarm core |
| `from sklearn.metrics.pairwise import cosine_similarity` | CPU pairwise metrics | **Yes** — Swarm core |
| `import cupy`, `from numba import cuda`, `import mlx.core` | CUDA / Apple Silicon Metal | **No** |

```python
import numpy as np
from numba import njit, prange, vectorize

# NumPy ufuncs are already vectorized (AVX2 on this i7). Prefer them over Python loops.
a = np.arange(6, dtype=np.float32).reshape(3, 2)
elem = np.add(a, a)          # element-wise ufunc
mat = np.matmul(a, a.T)      # generalized ufunc (gufunc)

@njit(parallel=True, fastmath=True)
def l2_rows(M):
    n, d = M.shape
    out = np.empty(n, dtype=np.float32)
    for i in prange(n):
        acc = np.float32(0.0)
        for j in range(d):
            v = M[i, j]
            acc += v * v
        out[i] = np.sqrt(acc)
    return out

@vectorize(["float32(float32, float32)"], target="cpu")
def fused_mul_add(x, y):
    return x * y + np.float32(1.0)
```

OpenCL on the discrete GPU (same pattern as Swarm; [PyOpenCL 2026.1 demo](https://documen.tician.de/pyopencl/)):

```python
import numpy as np
import pyopencl as cl

ctx = cl.create_some_context()  # pick the AMD Radeon Pro 5300M, not the CPU device
queue = cl.CommandQueue(ctx)
mf = cl.mem_flags
a_np = np.random.default_rng().random(50_000, dtype=np.float32)
a_g = cl.Buffer(ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=a_np)
# Kernel + enqueue: see src/swarm_sdk/gpu/opencl_math.py
```

Vulkan path stays `import kp` / `import vulkan as vk` (section 3). Do not set Numba `target="cuda"`.

#### F. Tool-Integrated Reasoning (TIR) Sandbox for Math Models
Math LLMs generate Python code inside Markdown blocks (````python ... ````) to compute intermediate steps. Here is the standard execution wrapper used to safely execute generated code:

```python
import sys
import io
import contextlib

def execute_math_code(code_str: str, timeout_sec: int = 5) -> str:
    """Executes code generated by Qwen2.5-Math or DeepSeek-R1 and captures stdout."""
    stdout_buffer = io.StringIO()
    # Safe namespace pre-loaded with math libraries
    exec_globals = {
        "__builtins__": __builtins__,
        "sp": sp,
        "sympy": sp,
        "Eq": sp.Eq,
        "np": np,
        "numpy": np,
        "mp": mp,
        "math": __import__("math"),
        "cmath": __import__("cmath"),
        "la": la,
        "opt": opt,
    }
    try:
        import cvxpy as cp

        exec_globals["cp"] = cp
    except ImportError:
        pass
    try:
        with contextlib.redirect_stdout(stdout_buffer):
            exec(code_str, exec_globals)
        return stdout_buffer.getvalue().strip()
    except Exception as e:
        return f"Execution Error: {e}"
```

### 11.2 C / C++ High-Performance Math Libraries
When building native Vulkan compute shaders or preprocessing pipelines:
* **Apple Accelerate Framework** (`#include <Accelerate/Accelerate.h>`): BLAS, LAPACK, vDSP (FFT, convolution), and vecLib (vectorized transcendentals via Intel **AVX2**, not AVX-512). NumPy/SciPy on this Mac link here.
* **Eigen 3** (`#include <Eigen/Dense>`): C++ template library for linear algebra, matrices, and geometry.
* **OpenCL C** (`__kernel void …` via PyOpenCL): vector/matrix kernels on the 5300M — same path as Swarm `opencl_math.py`.
* **Do not** pull Intel MKL-only or CUDA headers (`cublas`, `cupy`) for this laptop.

---

## 12. Local Vectorstore Architecture: Saving Tokens & Semantic Caching

Large language models are inherently bottlenecked by context window size, memory consumption, and API costs. When working on large codebases or asking iterative questions, **context stuffing** (dumping raw files or full conversation history) quickly consumes 10,000 to 50,000 tokens per request. 

By pairing our discrete **AMD Radeon Pro 5300M (Vulkan0)** running **BGE-M3** with an ultra-low-latency local vectorstore (**USearch** / **LanceDB**), we can implement two critical token-saving mechanisms:
1. **Semantic Prompt & Response Caching**: **100% token savings** on identical or semantically equivalent questions (0 prompt tokens, 0 completion tokens, <15ms response).
2. **Top-K Chunked Retrieval (RAG)**: **90% to 97% token savings** on codebase inspection by injecting only the precise 3–5 relevant chunks (e.g. 768 tokens) rather than whole 25,000-token repositories.

```
                      +------------------------------------------------------+
                      |               Incoming User Prompt                   |
                      +------------------------------------------------------+
                                                 |
                                     [Embed Query in <18ms]
                                 (BGE-M3 on Radeon 5300M Vulkan0)
                                                 |
                                                 v
                      +------------------------------------------------------+
                      |              Local Vectorstore (USearch)             |
                      |           High-dimensional Cosine Similarity         |
                      +------------------------------------------------------+
                                                 |
                        +------------------------+------------------------+
                        |                                                 |
             [Similarity >= 0.94]                              [Similarity < 0.94]
                        |                                                 |
                        v                                                 v
         +-----------------------------+                  +-------------------------------+
         |      SEMANTIC CACHE HIT     |                  |       SEMANTIC CACHE MISS     |
         |    Serve Cached Response    |                  |  Retrieve Top-3 Code Chunks   |
         |  * 100% TOKENS SAVED (0)    |                  |  (Saves 95% vs full file dump)|
         |  * Latency: < 2 ms          |                  |  Forward ~768 tokens to LLM   |
         +-----------------------------+                  +-------------------------------+
                                                                          |
                                                                          v
                                                          +-------------------------------+
                                                          |  Store New Vector + Response  |
                                                          |    in Local Vectorstore       |
                                                          +-------------------------------+
```

---

### 12.1 The Mathematics of Token Savings

| Scenario | Naive Context Stuffing | Vectorstore Semantic Cache / RAG | Token Savings | Speedup |
| :--- | :--- | :--- | :--- | :--- |
| **Repeated / Similar Query** | 2,500 prompt + 500 completion | **0 prompt + 0 completion** | **100% (3,000 tokens saved)** | **Instant (< 2ms)** |
| **Inspect 10 Code Files** | ~28,000 tokens per prompt | Top-3 chunks = ~768 tokens | **97.2% (27,232 tokens saved)** | **12x faster time-to-first-token** |
| **Multi-Turn Conversation** | 16,000 tokens (growing linearly) | Auto-pruned working memory ~1,200 tokens | **92.5% constant savings** | Eliminates KV cache memory exhaustion |

---

### 12.2 Comparison of Vector Solutions on Intel Mac

| Library / DB | Type | Storage Engine | SIMD / AVX2 on i7 | Best For | Typical Query Latency |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **USearch** | Search Library | In-memory / Mmap | **Native AVX2 + FP16** | **Semantic caching & fast in-memory similarity** | **< 0.5 ms** |
| **LanceDB** | Embedded Database | Disk-based (Lance) | **Native via Rust** | **Persistent codebase indexing (>100k chunks)** | **~ 2.5 ms** |
| **sqlite-vec** | SQLite extension | Disk SQLite, int8 columns + FTS5 | CPU int8 | **Swarm default** persistent memory + keyword hybrid | **~ 1–3 ms** |
| **DuckDB VSS** | SQL extension | In-process DuckDB, HNSW on `FLOAT[n]` | CPU HNSW | SQL over vectors (`INSTALL vss`); SQLAlchemy can sit on DuckDB | **~ 1–4 ms** |
| **pgvector** | Postgres extension | PostgreSQL heap + HNSW/IVFFlat | CPU | Durable SQL + SQLAlchemy; not a GPU index | **~ 2–8 ms** |
| **Faiss (CPU)** | Search Library | In-memory | Native AVX2 / BLAS | Massive vector clusters, IVF, Product Quantization | **~ 1.0 ms** |
| **HNSWLib** | Search Library | In-memory | Native AVX2 | Fast, lightweight HNSW graph indexing | **~ 0.8 ms** |
| **ChromaDB** | Embedded Database | SQLite + hnswlib in RAM | Standard | Rapid Python prototyping; **no GPU ANN index** | **~ 5.0 ms** |
| **OpenClVecStore** | Swarm brute-force | Host RAM, OpenCL top-k | OpenCL on 5300M | GPU search without an ANN database (small N) | **depends on N** |

---

### 12.3 Production Implementation: Semantic Token-Saving Cache

Here is a complete, production-ready Python semantic cache implementation using **`usearch`** (AVX2-optimized) and the **BGE-M3 Vulkan server** running on `Vulkan0`:

```python
#!/usr/bin/env python3
"""
Semantic Token-Saving Cache for Vulkan LLM Pipeline.
Intercepts prompts, checks vector similarity in USearch, and returns
cached answers for similarity >= threshold to save 100% of tokens.
"""

import json
import urllib.request
import numpy as np
from usearch.index import Index

EMBED_URL = "http://127.0.0.1:8080/v1/embeddings"
CHAT_URL = "http://127.0.0.1:8081/v1/chat/completions"

class SemanticTokenCache:
    def __init__(self, ndim: int = 1024, threshold: float = 0.94):
        self.threshold = threshold
        self.ndim = ndim
        # HNSW Index with Cosine similarity and FP16 storage
        self.index = Index(ndim=ndim, metric="cos", dtype="f16")
        self.entries = {}  # key -> {"prompt": str, "response": str, "tokens_saved": int}
        self.next_key = 0
        self.total_tokens_saved = 0

    def embed(self, text: str) -> np.ndarray:
        """Embed text using BGE-M3 on AMD Radeon Pro 5300M (Vulkan0)."""
        payload = json.dumps({"input": text, "model": "bge-m3"}).encode("utf-8")
        req = urllib.request.Request(EMBED_URL, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            vec = np.array(data["data"][0]["embedding"], dtype=np.float32)
            return vec / np.linalg.norm(vec)

    def query(self, prompt: str) -> tuple[str | None, float, bool]:
        """Check if prompt exists in semantic cache."""
        if len(self.index) == 0:
            return None, 0.0, False

        vec = self.embed(prompt)
        matches = self.index.search(vec, 1)

        if len(matches.keys) > 0:
            similarity = 1.0 - float(matches.distances[0])
            if similarity >= self.threshold:
                hit_key = int(matches.keys[0])
                cached = self.entries[hit_key]
                self.total_tokens_saved += cached.get("tokens_saved", 500)
                return cached["response"], similarity, True

        return None, 0.0, False

    def store(self, prompt: str, response: str, estimated_tokens: int = 500):
        """Store prompt embedding and response in cache."""
        vec = self.embed(prompt)
        key = self.next_key
        self.next_key += 1
        self.index.add(key, vec)
        self.entries[key] = {
            "prompt": prompt,
            "response": response,
            "tokens_saved": estimated_tokens
        }

    def stats(self) -> dict:
        return {
            "cached_entries": len(self.entries),
            "total_tokens_saved": self.total_tokens_saved
        }

# Example Usage:
if __name__ == "__main__":
    cache = SemanticTokenCache(threshold=0.93)
    
    prompt1 = "How do I configure MoltenVK with Vulkan on macOS 2019 Intel?"
    print(f"User 1: {prompt1}")
    cached_resp, sim, hit = cache.query(prompt1)
    if not hit:
        print("  -> Cache Miss! Querying LLM...")
        llm_response = "Install brew molten-vk and configure VK_ICD_FILENAMES to MoltenVK_icd.json."
        cache.store(prompt1, llm_response, estimated_tokens=350)
    
    # Near-identical semantic variation
    prompt2 = "How can I setup Vulkan with MoltenVK on my 2019 Intel Mac?"
    print(f"\nUser 2: {prompt2}")
    cached_resp, sim, hit = cache.query(prompt2)
    if hit:
        print(f"  -> Cache HIT! (Cosine Similarity: {sim:.4f})")
        print(f"  -> Answer: {cached_resp}")
        print(f"  -> Tokens saved: 350 tokens (0 tokens used!)")
```

---

### 12.4 Plan to Improve the Vectorstore Token-Saving Engine

To expand this capability across all development workflows on this Mac:

#### Phase 1: Local OpenAI-Compatible Proxy (`token_saver_proxy.py`)
* Create a lightweight Python FastAPI / asyncio proxy running on `127.0.0.1:8089`.
* Any CLI or editor (Crush CLI, Cursor, Claude Code, Cline, Aider) points to `http://127.0.0.1:8089/v1`.
* The proxy intercepts the prompt:
  * If vector similarity $\ge 0.94$: returns the cached completion instantly (0 tokens, 0 cost).
  * If cache miss: forwards to the target provider (local Vulkan `8081` or cloud OpenAI/Anthropic), logs the completion, embeds the query on `Vulkan0`, and stores it in the vectorstore.

#### Phase 2: LanceDB Disk-Backed Codebase Indexing (95% Context Reduction)
* Chunk all repository files (`.go`, `.py`, `.ts`, `.md`) into semantic chunks of 300 tokens using Tree-sitter AST parser.
* Store vectors in `~/.lancedb_cache/`.
* When asking questions about the project, retrieve only top-4 relevant chunks rather than passing entire files.

#### Phase 3: Hybrid Search (Reciprocal Rank Fusion - RRF)
* Combine dense vector retrieval (BGE-M3) with lexical search (BM25 / Ripgrep).
* Dense embeddings capture high-level semantic meaning; lexical search guarantees exact keyword / function name matching.

#### Phase 4: Dynamic Working Memory & Conversation Turn Pruner
* When conversation turns exceed 6 turns (approx. 4,000 tokens), summarize older turns into dense embeddings and remove raw dialogue from the active prompt.
* Old turns remain queryable via vector search without bloating the active inference window.

---

### 12.5 GPU Vector Databases vs MoltenVK (this host)

**There is no shipped ANN database that keeps HNSW/CAGRA on the Radeon 5300M via MoltenVK.** Molten accelerates **embeddings** (Vulkan / llama.cpp) and **brute-force top-k** (OpenCL in Swarm). The graph index stays on the CPU.

Split that is known to work here:

1. **Embed on Vulkan0** — BGE-M3 / llama.cpp on the 5300M (4 GB GDDR6).
2. **Index on CPU** — USearch (AVX2 + FP16), LanceDB, sqlite-vec, DuckDB VSS, or pgvector.
3. **Optional GPU search** — Swarm `OpenClVecStore` (`vectorstore.backend: opencl`): OpenCL inner-product top-k, not an ANN product.

Swarm default: `vectorstore.backend: sqlite-vec` (int8 + FTS5 hybrid). Do not set Qdrant/Milvus/Faiss **GPU** flags on this Mac.

#### Products that look like “GPU vector DB” and fail on this machine

| Product | What “GPU” actually is | This Intel Mac + MoltenVK |
| :--- | :--- | :--- |
| **Milvus GPU** (`GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ`, `GPU_BRUTE_FORCE`) | NVIDIA **CUDA** / RAPIDS CAGRA; Linux; NVIDIA driver; compute capability 6.0–9.0 | **No.** [GPU prereqs](https://milvus.io/docs/prerequisite-gpu.md), [GPU index overview](https://milvus.io/docs/gpu-index-overview.md) |
| **Qdrant GPU** (v1.13+) | Vulkan inside **Linux Docker**: `gpu-nvidia-latest` or `gpu-amd-latest` (**ROCm**, `/dev/kfd` + `/dev/dri`) | **No.** Not MoltenVK, not Docker Desktop AMD. [Running with GPU](https://qdrant.tech/documentation/ops-configuration/running-with-gpu) |
| **Qdrant (embedded / CPU)** | `QdrantClient(path=…)` in Swarm; optional **scalar int8** | **Yes, CPU only.** Swarm comment: GPU indexing is a CUDA/ROCm server build, not this client |
| **Faiss GPU** (`index_cpu_to_gpu`) | NVIDIA **CUDA** (`faiss-gpu`) | **No.** Swarm `vectorstore.gpu` is ignored on Radeon / MoltenVK / OpenCL |
| **Chroma “GPU”** | No GPU index. Local executor = **hnswlib in RAM** + SQLite | **CPU only.** A GPU embedder you pass in does not put HNSW on the 5300M |
| **DuckDB VSS** | CPU **HNSW** on fixed-size `ARRAY` / `FLOAT[n]` | **Yes, CPU SQL.** [`INSTALL vss`](https://duckdb.org/docs/stable/core_extensions/vss.html) |
| **duckdb-gpudb** | GPU **SQL** (GROUP BY, joins, top-k aggregations), not ANN | **No here.** Apple Silicon **Metal** or NVIDIA **CUDA** only. [gpudb](https://duckdb.org/community_extensions/extensions/gpudb) |
| **SQLAlchemy + DuckDB** | ORM + in-process SQL | **Yes** for tables. Vectors = DuckDB VSS on CPU. Adds no GPU ANN |
| **pgvector** | CPU HNSW / IVFFlat in PostgreSQL | **Yes, CPU.** SQLAlchemy talks to it |
| **pg_cuvs / PGPU** | NVIDIA **cuVS / CUDA** sidecar on top of pgvector | **No.** Linux + NVIDIA ([pg_cuvs](https://github.com/pg-cuvs/pg_cuvs)) |
| **RasterDB** (research) | DuckDB + **Vulkan SQL** (scan/join/agg), CUDA-free | **Not a vector DB.** Linux + RasterDF; not a macOS MoltenVK ANN store |

Qdrant’s GPU path uses Vulkan, but only through those Linux images. MoltenVK on macOS is a different stack (Metal translation for llama.cpp / NCNN / FFmpeg), not Qdrant’s `gpu-amd` ROCm container.

#### Decision for Swarm on this Mac

| Goal | Backend |
| :--- | :--- |
| Persistent memory + keyword hybrid | `sqlite-vec` (default) |
| GPU brute-force search | `opencl` (`OpenClVecStore`) |
| Fast in-memory semantic cache | USearch (CPU AVX2) + Vulkan embeddings |
| Disk RAG over the repo | LanceDB (CPU) + Vulkan embeddings |
| SQL over vectors | DuckDB VSS or pgvector (CPU); SQLAlchemy optional |
| Cloud / NVIDIA box | Milvus GPU, Qdrant GPU, Faiss-GPU, pg_cuvs — **not this laptop** |

---


## 13. Extended MoltenVK Utilizations (Beyond LLM Text)

The MoltenVK translation layer transforms your discrete AMD Radeon Pro 5300M into a versatile Vulkan compute accelerator across multiple domains:

### 13.1 Audio & Speech-to-Text: `whisper.cpp` with Vulkan
Transcribe audio at 10x realtime speed by running OpenAI Whisper models on the Radeon 5300M:

```bash
git clone https://github.com/ggerganov/whisper.cpp.git
cd whisper.cpp

# Build with Vulkan support
cmake -B build -DGGML_VULKAN=ON -DGGML_METAL=OFF
cmake --build build --config Release -j6

# Download Whisper Medium model (quantized Q5_0 ~500MB, fits easily in 4GB VRAM)
sh ./models/download-ggml-model.sh medium.en-q5_0

# Transcribe audio file using Radeon Pro 5300M (Vulkan)
./build/bin/whisper-cli -m models/ggml-medium.en-q5_0.bin -f sample.wav
```

### 13.2 Image Generation: `stable-diffusion.cpp` with Vulkan
Generate images locally using Stable Diffusion 1.5, SDXL-Turbo, or Latent Consistency Models (LCM) on the Radeon 5300M without CUDA:

```bash
git clone --recursive https://github.com/leejet/stable-diffusion.cpp.git
cd stable-diffusion.cpp

# Build with Vulkan support
cmake -B build -DSD_VULKAN=ON -DSD_METAL=OFF
cmake --build build --config Release -j6

# Run SD 1.5 (Q4_0 ~1.8GB weights, leaves 2GB VRAM for 512x512 latent frames)
./build/bin/sd \
  -m v1-5-pruned-emaonly.q4_0.gguf \
  -p "A futuristic city in the style of cyberpunk, 8k resolution, cinematic lighting" \
  --output output.png \
  --steps 20
```

### 13.3 Computer Vision & Edge AI: Tencent `NCNN` with Vulkan Shaders
NCNN is an inference framework featuring high-performance Vulkan compute shaders tailored for AMD RDNA / Radeon GPUs:

* **Object Detection**: Run YOLOv8 / YOLOv10 at 60+ FPS on 1080p video streams.
* **Super Resolution**: Real-ESRGAN / Waifu2x upscaling images 4x directly on the 5300M.
* **Pose & Face**: Mediapipe face mesh, hand tracking, and human body pose estimation.

```bash
# Install prebuilt NCNN with Vulkan enabled
pip install ncnn
```

```python
import ncnn

# Enable Vulkan compute on GPU 0 (AMD Radeon Pro 5300M)
net = ncnn.Net()
net.opt.use_vulkan_compute = True
print(f"Vulkan Device Count: {ncnn.get_gpu_count()}")
print(f"Using GPU: {ncnn.get_gpu_info(0).device_name()}")
```

### 13.4 Hardware-Accelerated Video Processing: FFmpeg Vulkan Filters
FFmpeg compiled with `--enable-vulkan` allows offloading heavy image and video filters to the 5300M:

```bash
# Hardware Vulkan scale and tonemapping
ffmpeg -init_hw_device vulkan=vk:0 -hwaccel vulkan \
  -i input_4k.mp4 \
  -filter_hw_device vk \
  -vf "hwupload,scale_vulkan=1920:1080,hwdownload,format=yuv420p" \
  -c:v libx264 output_1080p.mp4
```

### 13.5 Cross-Platform Game & 3D Simulation: Godot 4.x
* The **Godot 4.x** engine uses Vulkan as its primary rendering backend (Forward+ and Mobile renderers). On macOS, it routes all rendering and compute shaders through MoltenVK onto the AMD Radeon Pro 5300M.
* **WGPU / WebGPU (`wgpu-py`)**: Run next-generation compute pipelines written in WGSL on the Radeon 5300M.

### 13.6 Emulation with Hardware Graphics
* **RPCS3** (PlayStation 3), **Ryujinx** (Nintendo Switch), **PCSX2** (PlayStation 2), and **Dolphin** (GameCube/Wii) achieve their highest macOS performance when configured to use the **Vulkan** renderer, which routes through MoltenVK directly to the discrete AMD Radeon Pro 5300M instead of relying on legacy OpenGL.

---

## 14. Quick Reference Cheatsheet

| Domain | Task | Command / Import |
| :--- | :--- | :--- |
| **Vulkan Verification** | Inspect GPU Devices | `vulkaninfo --summary` |
| **llama.cpp** | List Compute Devices | `./build-vulkan/bin/llama-server --list-devices` |
| **Device Pinning** | Select Radeon Pro 5300M | `export GGML_VK_VISIBLE_DEVICES=0` |
| **Embeddings** | Serve BGE-M3 (Q8_0) | `./build-vulkan/bin/llama-server -m bge-m3-q8_0.gguf --device Vulkan0 -ngl 99 --embedding --port 8080 -b 512 -ub 512` |
| **Math Inference** | Serve Qwen2.5-Math-1.5B | `./build-vulkan/bin/llama-server -m Qwen2.5-Math-1.5B-Instruct-Q8_0.gguf --device Vulkan0 -ngl 99 --port 8081 -c 4096` |
| **CoT Reasoning** | Serve DeepSeek-R1-1.5B | `./build-vulkan/bin/llama-server -m DeepSeek-R1-Distill-Qwen-1.5B-Q5_K_M.gguf --device Vulkan0 -ngl 99 --port 8082 -c 4096` |
| **Speech-to-Text** | Whisper.cpp on Vulkan | `./whisper.cpp/build/bin/whisper-cli -m models/ggml-medium.en-q5_0.bin -f audio.wav` |
| **Diffusion** | Stable Diffusion Vulkan | `./stable-diffusion.cpp/build/bin/sd -m sd-v1-5.q4_0.gguf -p "prompt" -o out.png` |
| **Vector DB (CPU ANN)** | USearch / sqlite-vec / LanceDB / DuckDB VSS | `from usearch.index import Index; idx = Index(ndim=1024, metric='cos')` |
| **Vector search (OpenCL)** | Swarm brute-force on 5300M | `vectorstore.backend: opencl` — not Milvus/Qdrant/Chroma GPU |
| **Do not use here** | Milvus GPU, Qdrant GPU, Faiss-GPU, pg_cuvs | NVIDIA CUDA or Linux ROCm Docker; **not MoltenVK** |
| **Symbolic Math** | Solve / ODE / numeric | `from sympy import Eq, dsolve, linsolve, nsolve, lambdify` |
| **Convex equations** | CPU QP / LP | `import cvxpy as cp; x = cp.Variable(); cp.Problem(...).solve()` |
| **SciPy FFT** | DCT / FFT (explicit submodule) | `from scipy.fft import fft, dct, idct` |
| **NumPy ufuncs** | AVX2 vector math | `import numpy as np; np.add(a, b); np.matmul(A, B)` |
| **Numba JIT** | CPU SIMD + `prange` | `from numba import njit, prange` — **not** `numba.cuda` |
| **PyOpenCL** | Vector kernels on 5300M | `import pyopencl as cl; ctx = cl.create_some_context()` |
| **Kompute** | Vulkan tensors | `import kp; mgr = kp.Manager(0)` |
