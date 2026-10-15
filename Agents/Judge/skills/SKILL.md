---
name: JEVQualityGate
description: "TypeSafe AI JEV System One structured decision evaluator for the Judge agent. Executes calibrated Noul, Score, and Choice questions to audit code implementations, security postures, and benchmark claims."
---

# JEV System One Quality Gate Skill

## Overview

The `JEVQualityGate` skill equips the Judge agent with fast, structured decision evaluation via TypeSafe AI's Jev model (`POST https://api.typesafe.ai/v1/systemone`).

## Key Capabilities

1. **`Noul` Mechanical Gating**:
   - `passes_mechanical_gate`: Immediate binary evaluation of baseline syntax, test passing, and security sanity.
   - `is_sandbox_compliant`: Verifies strict isolation within designated workspace roots.
2. **`Score` Quantitative Scoring**:
   - Rates `correctness` (0.0-1.0), `security` (0.0-1.0), `performance` (0.0-1.0), and `maintainability` (0.0-1.0).
3. **`Choice` Verdict Routing**:
   - Classifies outcome into discrete verdicts (`APPROVED`, `APPROVED_WITH_NOTES`, `NEEDS_REVISION`, `REJECTED`).

## Authentication & Vault

Resolves `JEV_API_KEY` dynamically via `swarm_sdk.vault` from:
- `swarm/JEV_API_KEY` (macOS Keychain)
- `op://Swarm/JEV_API_KEY/credential` (1Password)
