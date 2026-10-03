# Prediction lane improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use [subagent-driven-development](../../../.cursor/skills-cursor/subagent-driven-development/SKILL.md) or [executing-plans](../../../.cursor/skills-cursor/executing-plans/SKILL.md). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the Prediction / `feat/prediction-engine` lane a reliable, testable forecasting feature (mlforecast + LightGBM) that matches the Newsletter/WebSearch lane pattern and stays mergeable into `main`.

**Architecture:** Keep **`Prediction/`** as a top-level package (not inside `src/swarm_sdk/` until a deliberate SDK hook is needed). Extend `ForecastEngine` with optional lag transforms and documented CV settings; add an offline benchmark task and MLSpecialist-facing docs. Sync the **`../Swarm-Prediction`** worktree with `main` before new feature commits so lane agents edit real files.

**Tech Stack:** Python `>=3.14.5`, uv, `forecast` extra (`lightgbm>=4.7.0`, `mlforecast>=1.1.0`), pandas, pytest.

**Spec:** Lane contract [`.cursor/agents/prediction-lane.md`](../../.cursor/agents/prediction-lane.md), epic [`Agents/coordination.yaml`](../../Agents/coordination.yaml) `prediction_forecast`, existing [`Prediction/engine.py`](../../Prediction/engine.py).

## Global Constraints

- Work only on branch **`feat/prediction-engine`** in **`../Swarm-Prediction`** (or root checkout on that branch); do **not** create new branches/worktrees ([`git-docs.mdc`](../../.cursor/rules/git-docs.mdc)).
- Only one lane owns root **`uv.lock`** per integration window; Prediction changes lockfile only on this branch, then merge to `main`.
- No secrets in YAML; env var **names** only if added later.
- Quality gate after code: `uv run --extra forecast pytest tests/test_prediction_engine.py -q` plus full repo gate before integration merge.
- After API/library edits: **Context7** (`/nixtla/mlforecast`) → **Context.dev** / **Tavily** if flags mismatch.

## Review Focus

1. **Lane drift:** `feat/prediction-engine` is **9 commits behind `main`** and currently has **no `Prediction/` tree** — worktree edits fail silently if not merged first.
2. **Tooling gap:** `Prediction/` is **outside** `[tool.ruff] src` — lint/type gate may skip lane code until paths are added.
3. **Backtest semantics:** `cross_validation` needs explicit **`step_size`** / min history vs `min_rows_per_series` — easy to pass tests but fail on real series.
4. **Optional deps:** CI without `--extra forecast` must not import LightGBM at collection time (keep lazy imports in `_build()`).
5. **Integration scope creep:** Swarm orchestrator / gRPC wiring is a **separate** epic unless a thin, testable adapter is scoped.

## Current state (2026-10-03)

| Item | Status |
| :--- | :--- |
| `Prediction/engine.py` + tests on **`main`** | Present (`8fca3a7`); **9 tests pass** with `--extra forecast` |
| `../Swarm-Prediction` @ `feat/prediction-engine` | **Missing `Prediction/`**; branch **9↓ / 0↑** vs `main` |
| `coordination.yaml` `prediction_forecast` | `in_progress` |
| Swarm persona / benchmark task | **Not** added (Newsletter lane has persona + tests; Prediction does not) |
| mlforecast usage | Minimal: global LGBM, lags + `date_features`, `cross_validation(h, n_windows)` only |

---

## Phase 0 — Lane sync (blocking)

- [ ] **0.1** In `../Swarm-Prediction`: `git fetch origin && git merge origin/main` (or merge local `main` if same remote). Resolve `uv.lock` with **`uv lock`** if conflict.
- [ ] **0.2** Verify: `Prediction/engine.py` and `tests/test_prediction_engine.py` exist; `uv run --extra forecast pytest tests/test_prediction_engine.py -q` green.
- [ ] **0.3** Update [`.cursor/agents/prediction-lane.md`](../../.cursor/agents/prediction-lane.md) if merge changed gate paths (optional one line: “sync `main` before feature work”).

**Done when:** worktree matches `main` for Prediction paths and tests pass.

---

## Phase 1 — Package hygiene & docs (small, merge-ready)

- [ ] **1.1** Add [`Prediction/README.md`](../../Prediction/README.md): long-format schema (`unique_id`, `ds`, `y`), install (`uv sync --extra forecast`), minimal fit/predict/backtest example, link to mlforecast docs.
- [ ] **1.2** Extend `pyproject.toml` **`[tool.ruff] src`** (and **`ty`** / pytest paths if applicable) to include **`Prediction`** and **`tests/test_prediction_engine.py`** parent — run `uv run --extra dev ruff check Prediction tests/test_prediction_engine.py`.
- [ ] **1.3** Fix pandas **`Timedelta(days=120)`** deprecation in tests (use explicit unit); keep assertions unchanged.
- [ ] **1.4** README root table row for Prediction: note worktree sync + forecast extra (one paragraph max).

**Done when:** ruff clean on Prediction; tests green; README exists.

---

## Phase 2 — Engine improvements (Context7-backed)

Reference: [mlforecast cross_validation](https://github.com/nixtla/mlforecast) — `step_size`, `lag_transforms`, `num_threads=1` for deterministic CI on 6c host.

- [ ] **2.1** **Failing test:** `ForecastConfig` accepts optional `lag_transforms` (e.g. `{7: [RollingMean(window_size=7)]}`) and engine passes them to `MLForecast` — verify predict shape unchanged on synthetic data.
- [ ] **2.2** **Implement:** import transforms from `mlforecast.lag_transforms`; default `None` preserves current behavior.
- [ ] **2.3** **Failing test:** `backtest(..., step_size=...)` forwarded to `cross_validation` (default `step_size=horizon` for non-overlapping windows).
- [ ] **2.4** **Implement:** document minimum rows formula in docstring: `max(lags) + 1 + horizon * n_windows + (n_windows - 1) * step_size` (adjust validation accordingly).
- [ ] **2.5** **Optional (YAGNI gate):** `ForecastEngine.from_csv(path)` helper for CLI/benchmark — only if Phase 3 needs it.
- [ ] **2.6** Context7 pass on `MLForecast(...)` kwargs used; fix any renamed/deprecated flags.

**Done when:** new tests pass; no change to default config behavior on existing tests.

---

## Phase 3 — Benchmark task (Agents/benchmark)

Mirror [`Tasks/cold_import/`](../../Agents/benchmark/Tasks/cold_import/) and [`Tasks/rag_quality/`](../../Agents/benchmark/Tasks/rag_quality/) patterns.

- [ ] **3.1** Add `Agents/benchmark/Tasks/prediction_forecast/`:
  - `task.yaml` — `sdk_entry`, metrics (`mae`, `rmse` on synthetic sine), `models: none`
  - `benchmark_prediction_forecast.py` — builds `_frame()`-like data, runs `ForecastEngine.backtest`, writes optional JSON to `results/prediction_forecast/` (gitignored)
  - `test_prediction_forecast.py` — quick mode asserts MAE below threshold on clean signal
- [ ] **3.2** Document in [`Agents/benchmark/README.md`](../../Agents/benchmark/README.md) and [`Agents/MLSpecialist/Benchmarks/README.md`](../../Agents/MLSpecialist/Benchmarks/README.md).
- [ ] **3.3** Run: `uv run --extra forecast pytest Agents/benchmark/Tasks/prediction_forecast -q`.

**Done when:** benchmark task is offline, no API keys, CI-friendly `--quick`.

---

## Phase 4 — Swarm coordination (optional MVP)

Only if product goal includes orchestrated forecasts (not required for Phase 1–3).

- [ ] **4.1** Add `Agents/Prediction/agent.yaml` + minimal `AGENTS.md` (task `forecast_series`, JSON contract: `status`, `horizon`, `metrics_path` or inline `metrics` summary — **no** raw series dump in logs).
- [ ] **4.2** Register in [`Agents/SKILLS.md`](../../Agents/SKILLS.md); run `uv run python -m swarm_sdk.agents.validate`.
- [ ] **4.3** Set `prediction_forecast` epic **`status: done`** in `coordination.yaml` when Phases 0–3 complete (Phase 4 optional).

**Done when:** validate passes; epic status reflects reality.

---

## Phase 5 — Integration merge

- [ ] **5.1** From lane branch: ensure single lockfile owner — `uv lock` if deps changed.
- [ ] **5.2** Merge **`feat/prediction-engine` → `main`** (via `integration/all-branches` if that is active policy).
- [ ] **5.3** Full gate on `main`: forecast tests + `pytest Agents/benchmark -q` + ruff/ty/validate.

---

## Suggested execution order

```text
Phase 0 (sync) → Phase 1 (hygiene) → Phase 2 (engine) → Phase 3 (benchmark)
       → Phase 4 (persona, optional) → Phase 5 (merge)
```

## Out of scope (defer)

- HTTP/gRPC forecast endpoints on `swarm-api`
- GPU / OpenCL time-series kernels
- Live market data ingest (WebSearch lane)
- Replacing LightGBM with neural forecasters (Nixtla `neuralforecast`)

## Verification matrix

| Check | Command |
| :--- | :--- |
| Forecast unit tests | `uv run --extra forecast pytest tests/test_prediction_engine.py -q` |
| Benchmark task | `uv run --extra forecast pytest Agents/benchmark/Tasks/prediction_forecast -q` |
| Lane worktree | `cd ../Swarm-Prediction && git status && test -f Prediction/engine.py` |
| Agents | `uv run python -m swarm_sdk.agents.validate` |
| Full gate | See root `AGENTS.md` quality gate |
