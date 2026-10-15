# BGE-M3 Q8_0 + SQLite INT8 smoke check

Date: 2026-09-29. This uses 16 deterministic, improvised text snippets and a
temporary SQLite file; it does not open or modify the configured memory DB.

- Model: `bge-m3-q8_0.gguf`, GGUF Q8_0, 567M parameters, 598.63 MiB.
- llama.cpp logged `offloaded 25/25 layers to GPU` and assigned layers to
  `Vulkan0 (AMD Radeon Pro 5300M)`. The produced array was `(16, 1024)` float32;
  document-batch embedding took 2.2584 s.
- The native sqlite-vec extension loaded. Stored vectors had 1024-byte INT8
  payloads. One top-5 SQL vector search took 1.971 ms over 16 rows.
- This SQLite has no FTS5 module. The store now creates a regular fallback
  table and handles keyword matching without FTS5.
- PyOpenCL selected `AMD Radeon Pro 5300M Compute Engine` when explicitly
  requested. Native sqlite-vec search does not call OpenCL, so that search ran
  inside SQLite on CPU.
- The first retrieved synthetic item contained the requested AMD Radeon GPU
  context, but a few unrelated snippets also ranked highly. This smoke confirms
  that the pipeline runs; it is not a semantic retrieval quality claim.

The full result is in `smoke.json`; `int8_gpu_vectorized_llama.log` records the
llama.cpp backend and layer offload details. Focused verification:

```bash
uv run pytest Agents/tests/test_memory.py Agents/tests/test_llama_embedder.py Agents/tests/test_config.py -q
uv run ruff check src/swarm_sdk/memory/sqlite_vec.py src/swarm_sdk/retrieval/embeddings.py Agents/tests/test_memory.py Agents/tests/test_llama_embedder.py
```

Result: 22 passed, 2 skipped; Ruff passed.
