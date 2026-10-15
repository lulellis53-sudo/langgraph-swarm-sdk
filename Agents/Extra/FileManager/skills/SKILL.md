---
name: FileManagerSkill
description: "Universal file extraction, static reverse engineering, and data serialization format conversion skill."
---

# FileManager Skill Specification

## 1. Overview
The `FileManagerSkill` equips `FileManager` with automated routines for deep archive decompression, Mach-O/ELF binary disassembly, and zero-loss structured data format cross-compilation.

## 2. Capabilities
1. **Archive Decompression**: Multi-threaded extraction via `tar`, `unzip`, `zstandard`, and `7z`.
2. **Static Reverse Engineering**: Inspects binary headers (`otool`, `llvm-objdump`, `nm`), disassembles machine instructions, extracts text symbols, and reconstructs data structures.
3. **Format Cross-Compilation**: High-speed schema-preserving conversion between JSON, YAML, TOML, Parquet, Arrow, CSV, and Protobuf.
4. **Text & Delimited CSV Conversion**: Samples raw text files to infer delimiters, headers, and column definitions, producing strictly validated RFC 4180 CSV tables.
