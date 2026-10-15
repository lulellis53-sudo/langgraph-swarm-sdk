# Compilator Skill: DevEnvironmentArchitect Engine

> **Scope**: Maintain reproducible developer environments using Pixi, Nix, or Homebrew; pin toolchain dependencies (LLVM, CPython, Node.js, Rust), and align developer environment configurations with CI runners.

---

## 1. Developer Environment Architecture

### 1.1 Toolchain Pinning & Reproducibility Protocol
1. Pin exact toolchain versions across Pixi (`pixi.toml`), Cargo (`Rust-toolchain.toml`), and Homebrew environments.
2. Align local developer environment configurations with CI runner flags.
3. Configure shell hooks and environment variables (`zshenv.zsh`, `local.zsh`) to enforce deterministic build behavior.

---

## 2. Environment Alignment Matrix

| Tool | Purpose | Primary Manifest |
| :--- | :--- | :--- |
| **Pixi** | Cross-platform package & environment management | `pixi.toml` / `pixi.lock` |
| **Cargo / Rustup** | Rust compiler & target pinning | `rust-toolchain.toml` |
| **LLVM / Clang** | Native compiler & LTO optimization | `zshenv.zsh` / `LLVM23_HOME` |
| **Homebrew** | Host system dependencies | `Brewfile` |
