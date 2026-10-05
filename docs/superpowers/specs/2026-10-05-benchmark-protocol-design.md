# One benchmark protocol for Agents/benchmark — design

Date: 2026-10-05 · Status: awaiting review

## Goal

`Agents/benchmark/protocol.py` is the only place that computes a latency summary or an A/B claim inside `Agents/benchmark`. A measured difference may be published from one session. A speedup claim may not.

Success: the GPU tasks and the agent-suite span rows call `latency_report`; cold import, evals, efficiency gains, and wave fail-fast call `comparison_row`; their existing `improvement_pct` tests still pass; `claim` is `"none"` on a single run.

## Decision

Add two helpers to `benchmark.protocol` and call them from the existing tasks. Do not add a report class. Do not leave a second copy of the percentile or the improvement formula.

## Helpers

### `latency_report(samples: list[float]) -> dict[str, object]`

Calls `summarize` once. Returns `n`, `p50_ms`, `median_ms`, `p95_ms`, `p99_ms`, `mad_ms`, `mean_ms`, `stdev_ms`, `cv_pct`, and `tail_supported`. `median_ms` equals `p50_ms`.

`p95_ms` and `p99_ms` are the nearest-rank values when `tail_supported` is true (`n >= 100`). Otherwise both are `null`. Fewer than two finite samples raises `ValueError`, the same error `summarize` raises.

`suite.latency_distribution` returns that dict unchanged. It does not call `summarize` again and it does not compute a percentile.

### `comparison_row`

```python
def comparison_row(
    name: str,
    baseline: float,
    current: float,
    *,
    higher_is_better: bool,
    detail: dict[str, object] | None = None,
    independent_runs: int = 1,
    dispersion: float | None = None,
) -> dict[str, object]:
```

Returns `name`, `baseline`, `current`, `improvement_pct`, `delta_pp`, `higher_is_better`, `detail`, and `claim`. An omitted `detail` is `null`.

`baseline` and `current` are rounded to 4 decimal places. `delta_pp` is `current - baseline`, rounded to 4 decimal places. When `baseline` is non-zero and both values are finite, `improvement_pct` is `(current - baseline) / baseline * 100`, negated when `higher_is_better` is false, then rounded to 2 decimal places. When `baseline` is zero or either value is non-finite, `improvement_pct` is `null`. That matches the four local `_metric` functions. A bad pair does not raise.

`claim` is `"win"` only when `dispersion` is a finite number greater than or equal to zero and `allows_speedup_claim` returns true for `delta = current - baseline`. Otherwise `claim` is `"none"`. The four task callers pass one session and omit `dispersion`, so their claim stays `"none"`.

## Call sites

| Caller | Change |
| --- | --- |
| `Tasks/gpu_retrieval/benchmark_gpu_retrieval.py` | Delete `_percentile`. Fill `p50_ms`, `p95_ms`, `mad_ms`, `cv_pct`, `n`, and `tail_supported` from `latency_report`. |
| `Tasks/gpu_quantization/benchmark_gpu_quantization.py` | Same latency fields. Its winner stays the qualifying mode with the smallest `resident_vector_bytes`. |
| `Tasks/agent_suite/instruments.py` | Each span row keeps `name`, `mode`, and `count`. A group with at least two durations also stores the `latency_report` fields. A shorter group sets `p50_ms`, `p95_ms`, and `p99_ms` to null. Delete `_median` and `_nearest`. |
| `Tasks/agent_suite/suite.py` | `latency_distribution` returns `latency_report` unchanged. |
| `Tasks/cold_import/benchmark_cold_import.py` | Delete `_metric`. Call `comparison_row`. |
| `Tasks/Evals/benchmark_evals.py` | Delete `_metric`. Call `comparison_row`. |
| `Tasks/efficiency_gains/benchmark_efficiency_gains.py` | Delete `_metric`. Call `comparison_row`. |
| `Tasks/wave_fail_fast/benchmark_wave_fail_fast.py` | Delete `_metric`. Call `comparison_row`. |

## GPU retrieval winner

The default workload uses 50 queries, so `tail_supported` is false and `p95_ms` is null. The winner is the eligible profile with the lowest `p50_ms`. Eligible still means `recall_at_k >= 0.999`, falling back to all profiles when none qualify. When `tail_supported` is true, the winner is the eligible profile with the lowest `p95_ms`. The report field `selection` states which key was used. `queries < 2` raises `ValueError` before any search.

NumPy's linear percentile and nearest-rank are different numbers. Published tails follow nearest-rank.

## Out of scope

RSS conversion stays in the callers that already have it. `python315_claims` keeps its own median timer. No pyperf and no pytest-benchmark. No change to the meaning of `improvement_pct`.

## Tests

In `Agents/benchmark/tests/test_benchmark_protocol.py`:

- 30 finite samples: both tails null, `tail_supported` false.
- 100 finite samples: tails equal the nearest-rank values, `tail_supported` true.
- `comparison_row` matches the current sign, rounding, and zero-baseline behavior.
- One run, or a missing `dispersion`, does not claim a win.
- Two runs, a non-zero delta, and zero dispersion do claim a win.

One GPU retrieval test builds two profiles and checks that a withheld tail ranks them by `p50_ms`, and a supported tail ranks them by `p95_ms`. No GPU run.

The existing cold-import, evals, efficiency, and wave tests stay unchanged and must still pass.
