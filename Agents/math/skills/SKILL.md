---
name: math-interactive-calculator
description: Use the 2+2 Calculator app when the user asks for an interactive calculator or wants an expression prefilled in one. Do not use it as the math agent's verification engine.
---

# Math Interactive Calculator

## App tool

- App: `2+2 Calculator`
- Tool: `mcp__codex_apps__2_2_calculator_calculator`
- Use it to open an interactive calculator, select plain or scientific layout,
  choose degrees or radians, and prefill a supported expression when requested.

## Usage rules

- Invoke the app only when the user asks for a calculator widget or asks to
  continue evaluating an expression interactively.
- The tool accepts a structured expression tree, not arbitrary expression text.
  Build only from the supported number, unary, and binary operations in its
  current tool schema.
- Keep derivations, proofs, and reproducible numeric verification in the
  math agent's symbolic or scripted workflow. The widget is an interactive
  convenience and is not evidence that a result is correct.
- If the app tool is unavailable to the active agent, explain that limitation
  and continue with the available deterministic math tools.
