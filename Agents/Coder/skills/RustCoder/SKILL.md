---
name: RustCoderSkill
description: Specialist Rust 1.99+, Cargo, Clippy, and Memory Safety skill for Coder agent.
---

# RustCoder Skill Guide

> **Purpose**: Equip the **Coder** agent with idiomatic Rust 1.99+ coding practices, strict Clippy verification (`-D warnings`), memory-safety invariants, and Cargo unit/integration test workflows.

---

## 1. Rust Toolchain

| Component | Standard Tool | Command |
| :--- | :--- | :--- |
| **Compiler** | Rustc 1.99+ (`cargo`) | `cargo --version` |
| **Formatting** | Rustfmt | `cargo fmt --check` |
| **Linter** | Clippy | `cargo clippy --all-targets -- -D warnings` |
| **Test Runner** | Cargo Test | `cargo test --all-targets` |

---

## 2. Coding Guidelines & Invariants
- Prefer safe Rust. Any `unsafe` block MUST include an explicit safety comment (`// SAFETY: ...`) explaining raw pointer/memory invariants.
- Use explicit error handling (`Result<T, E>`, `Option<T>`). Never call `.unwrap()` or `.expect()` in production library code.
- Handle ownership, borrowing, and lifetimes cleanly without unneeded `.clone()` calls.
