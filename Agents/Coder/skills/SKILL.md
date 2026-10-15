---
name: MultiLanguageCoder
description: Multi-language programming skill for Python, Rust, C/C++, Golang, Node.js, and TypeScript. Provides specialized toolchain commands, linter flags, build flags, and idiomatic coding patterns for Coder.
---

# MultiLanguageCoder Skill Guide

> **Purpose**: Equip the unified **Coder** agent with specialized multi-language toolchain capabilities, idiomatic conventions, and strict verification commands across Python, Rust, C/C++, Golang, Node.js, and TypeScript.

---

## Language Toolchain Matrix

| Language | Primary Compiler / Runtime | Formatting & Linting | Type Checking / Static Analysis | Recommended Test Runner |
| :--- | :--- | :--- | :--- | :--- |
| **Python** | Python 3.14/3.15 (`uv`) | `uv run ruff check` / `ruff format` | `uv run pyright` | `uv run pytest -v` |
| **Rust** | Rustc 1.99 (`cargo`) | `cargo fmt` / `cargo clippy` | `cargo check` | `cargo test --all-targets` |
| **C / C++** | LLVM Clang 23 (`cmake`/`ninja`) | `clang-format -i` / `clang-tidy` | `cppcheck` / Polly-LLVM analysis | `ctest --output-on-failure` / `ninja test` |
| **Golang** | Go 1.24+ (`go`) | `gofmt -w` / `golangci-lint` | `go vet` | `go test -v ./...` |
| **Node.js / TS** | Node v26 / Bun (`pixi`) | `biome check` / `prettier -w` | `tsc --noEmit` | `vitest` / `jest` / `node --test` |

---

## 1. Python Specialist Guidelines
- **Style**: Follow Google Python Style Guide with explicit type annotations and Google-style docstrings (`Args:`, `Returns:`).
- **Toolchain**: Use `uv` for instant environment execution. Avoid raw `pip` or system python modifications.
- **Verification Commands**:
  ```bash
  uv run ruff check path/to/file.py --fix
  uv run pyright path/to/file.py
  uv run pytest tests/test_module.py -v
  ```

---

## 2. Rust Specialist Guidelines
- **Safety**: Prefer safe Rust. Unsafe blocks require explicit safety comments (`// SAFETY: ...`) detailing raw pointer invariants.
- **Toolchain**: Use `cargo` with Clippy warnings set to deny (`-D warnings`).
- **Verification Commands**:
  ```bash
  cargo fmt --check
  cargo clippy --all-targets -- -D warnings
  cargo test --all-targets
  ```

---

## 3. C / C++ Specialist Guidelines
- **Standards**: Target Modern C++20/C++23 or C17. Enforce strict compiler flags (`-Wall -Wextra -Werror -pedantic`).
- **Memory & Allocators**: Check pointer bounds and memory leaks. Use RAII (`std::unique_ptr`, `std::shared_ptr`).
- **Verification Commands**:
  ```bash
  clang-format --dry-run --Werror path/to/file.cpp
  cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug
  ninja -C build
  ctest --test-dir build --output-on-failure
  ```

---

## 4. Golang Specialist Guidelines
- **Idioms**: Enforce explicit error handling (`if err != nil`). Never swallow errors. Keep interfaces small and focused.
- **Concurrency**: Prevent goroutine leaks using contexts (`context.Context`) and channel select timeouts.
- **Verification Commands**:
  ```bash
  gofmt -s -w .
  go vet ./...
  golangci-lint run
  go test -v -race ./...
  ```

---

## 5. Node.js & TypeScript Guidelines
- **Types**: Enforce `strict: true` in `tsconfig.json`. Avoid `any`; use `unknown` with type narrowing guards.
- **Module Format**: Target ESM (`"type": "module"`). Use standard Web APIs (`fetch`, `StructuredClone`, `crypto`).
- **Verification Commands**:
  ```bash
  npx tsc --noEmit
  npx biome check .
  npx vitest run
  ```
