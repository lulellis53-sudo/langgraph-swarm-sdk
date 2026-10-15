# CPython 3.14.7 / Radeon OpenCL retrieval measurements

- Host: x86_64 Intel MacBook Pro, AMD Radeon Pro 5300M Compute Engine via Apple OpenCL.
- Python: 3.14.7. Swarm's `.venv` uses the same CPython 3.14.7 base prefix; standalone interpreter path: `.runtime/cpython-3.14.7/bin/python3.14`.
- Dataset: deterministic normalized float32 Gaussian vectors, seed 7. Inputs are in each workload's `synthetic_vectors.npz`; no user data was read.
- Correctness: 8192×384 OpenCL dot output matched NumPy, max absolute error `5.340576171875e-05`.
- Retrieval tests: AMD-selected `Agents/tests/test_gpu_math.py`, with `SWARM_OPENCL_MIN_ROWS=1`: 7 passed. This override makes the small correctness cases execute on the GPU.

## 2048 rows × 384 dimensions

Command:

```bash
SWARM_OPENCL_DEVICE='AMD Radeon Pro 5300M' .venv/bin/python \
  Agents/benchmark/Tasks/gpu_retrieval/benchmark_gpu_retrieval.py \
  --rows 2048 --dim 384 --queries 20 --k 10
```

All profiles had recall@10 `1.0`. Best NumPy p95: `0.211 ms` (chunk 4096). Best OpenCL p95: `4.127 ms` (chunk 4096). Recommendation: NumPy.

## 8192 rows × 1024 dimensions

Command:

```bash
SWARM_OPENCL_DEVICE='AMD Radeon Pro 5300M' .venv/bin/python \
  Agents/benchmark/Tasks/gpu_retrieval/benchmark_gpu_retrieval.py \
  --rows 8192 --dim 1024 --queries 10 --k 10
```

All profiles had recall@10 `1.0`. Best NumPy p95: `1.917 ms` (chunk 4096). Best OpenCL p95: `83.190 ms` (chunk 4096). Recommendation: NumPy.

The benchmark forces OpenCL for the comparison sweep. These measurements show no retrieval speedup for OpenCL at the tested sizes; keep runtime defaults unchanged until larger workloads or a lower-overhead kernel are measured.
