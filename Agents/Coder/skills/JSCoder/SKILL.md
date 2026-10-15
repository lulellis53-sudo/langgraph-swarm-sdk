---
name: JSCoderSkill
description: Specialist JavaScript, TypeScript, Node.js v26, Bun, and Web API skill for Coder agent.
---

# JSCoder Skill Guide

> **Purpose**: Equip the **Coder** agent with JavaScript/TypeScript standards, ESM module rules, type-checking (`tsc`), linting (`biome`), and modern test runners (`vitest`, `jest`, `node --test`).

---

## 1. JavaScript & TypeScript Toolchain

| Component | Standard Tool | Command |
| :--- | :--- | :--- |
| **Runtime** | Node.js v26 / Bun (`pixi`) | `node -v` / `bun -v` |
| **Lint & Format** | Biome / Prettier | `npx biome check .` / `npx prettier -w .` |
| **Type Check** | TypeScript Compiler | `npx tsc --noEmit` |
| **Test Runner** | Vitest / Jest / Native | `npx vitest run` / `node --test` |

---

## 2. Coding Guidelines & Invariants
- Target strict ESM (`"type": "module"` in `package.json`).
- Enforce `strict: true` in `tsconfig.json`. Disallow `any` types; use `unknown` with type guards.
- Prefer standard Web APIs (`fetch`, `StructuredClone`, `Web Crypto`) over third-party dependencies when available.
