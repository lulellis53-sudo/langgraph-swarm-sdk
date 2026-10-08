# Research Dossier: Lightweight LLM Engine Architectures

## 1. Executive Summary & Core Recommendation
For efficient edge and private cloud deployments, transitioning from bloated legacy serving frameworks to high-throughput, memory-efficient LLM engines (vLLM, llama.cpp, SGLang) is critical. Implementing INT4/INT8 GGUF scalar quantization drastically reduces VRAM requirements while maintaining near-fp16 fidelity. **Core Recommendation:** Standardize on **vLLM** for datacenter high-throughput (PagedAttention) and **llama.cpp / FastEmbed** for edge/CPU inference, secured via **farm-keychain** for microsecond-latency routing.

## 2. ASCII Multipath Decision Flow Diagram
```text
[ Incoming Request ] -> [ farm-keychain Auth ]
        |
   [ Target Hardware ]
    /               \
[ NVIDIA GPU ]    [ CPU / Apple Silicon ]
      |                   |
    vLLM              llama.cpp
  (AWQ/FP8)          (GGUF INT4/INT8)
      |                   |
      +-------+-----------+
              |
        [ Response ]
```

## 3. Technical Breakdown (Data Flow, State & Concurrency)
- **vLLM & PagedAttention:** Solves KV cache memory fragmentation by allocating memory in non-contiguous pages, achieving 2-4x higher throughput.
- **SGLang:** Employs RadixAttention to cache structured prompt prefixes (e.g., system prompts, agent templates) automatically, reducing TTFT (Time To First Token) for swarm workflows.
- **INT4/INT8 GGUF Scalar Quantization:** Efficient weight representation that dramatically reduces bandwidth bottlenecks. GGUF format allows unified cross-platform distribution.
- **FastEmbed:** Micro-framework for high-speed, CPU-first text embeddings using ONNX runtime, circumventing heavy PyTorch dependencies.
- **Microsecond Latency Routing:** Using ultra-fast proxies (e.g., Rust/Go based) coupled with `farm-keychain` ensures that token authentication adds < 1ms to the routing envelope.

## 4. Comprehensive Code Imports & Setup
```python
# vLLM Engine Initialization
from vllm import LLM, SamplingParams

llm = LLM(model="meta-llama/Llama-3-8b", quantization="awq", gpu_memory_utilization=0.9)
params = SamplingParams(temperature=0.2, max_tokens=256)

# FastEmbed Setup
from fastembed import TextEmbedding
embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
```

## 5. Comparative Analysis & Trade-Off Matrix
| Engine | Backend | Optimization | Best Use Case |
|---|---|---|---|
| vLLM | PyTorch/CUDA | PagedAttention | High-throughput GPU inference |
| llama.cpp | C/C++ (ggml) | GGUF Quantization | Edge, CPU, Mac environments |
| SGLang | PyTorch | RadixAttention | Complex multi-turn prompt reuse |
| FastEmbed | ONNX | Zero PyTorch Overhead | Standalone CPU embedding generation|

## 6. Hardware Performance Benchmarks & Deltas
- vLLM vs HuggingFace Accelerate: ~3.5x throughput increase for batched requests.
- GGUF INT4 vs FP16: ~70% VRAM reduction, ~2x memory bandwidth speedup, < 1% perplexity degradation.
- FastEmbed vs SentenceTransformers: ~3x faster inference on CPU.

## 7. Edge Cases, Pitfalls & Failure Modes
- **PagedAttention Overhead:** For extremely small batches (batch size = 1), vLLM overhead can sometimes slightly degrade latency compared to bare-metal TensorRT.
- **GGUF Model Drift:** Over-quantization (e.g., INT2) leads to catastrophic capability collapse.
- **farm-keychain Bottlenecks:** If authentication caching is not utilized, API validation latency may overshadow TTFT on fast edge models.

## 8. Primary Citations & Evidence Ledger
- vLLM GitHub Repository: [https://github.com/vllm-project/vllm](https://github.com/vllm-project/vllm)
- llama.cpp GitHub Repository: [https://github.com/ggerganov/llama.cpp](https://github.com/ggerganov/llama.cpp)
- Qwen/SGLang Documentation.
