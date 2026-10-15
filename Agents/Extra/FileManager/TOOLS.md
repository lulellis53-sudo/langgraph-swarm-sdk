# Agent Tools Specification: FileManager

> **Authoritative Specification**: Tooling, binary inspection engines, and format conversion utilities for `FileManager`.

---

## 1. Core Tooling Catalog

1. **Extraction & Archive Engines**:
   - `tar`: Tape archive extractor (`tar -xzf`, `tar -xjf`).
   - `unzip`: ZIP archive extraction.
   - `zstd`: Zstandard decompression (`zstd -d`).
   - `7z`: 7-Zip high-compression extractor.
2. **Reverse Engineering & Binary Analysis**:
   - `llvm-objdump`: Disassembler and object dumper (`~/.local/opt/llvm-23.1.1/bin/llvm-objdump`).
   - `otool`: macOS native Mach-O header and section dumper (`otool -h -l -tvV`).
   - `nm`: Symbol table extractor.
   - `strings`: ASCII/Unicode string extraction (`strings -a`).
   - `hexdump` / `xxd`: Raw binary byte inspection.
3. **Format Cross-Compilation Libraries**:
   - `orjson`: Fast JSON serialization/deserialization.
   - `polars` / `pyarrow`: High-performance columnar data conversion (CSV <-> Parquet <-> Arrow).
   - `tomlkit`: Format-preserving TOML editor.
   - `protobuf`: Protocol Buffers encoder/decoder.
