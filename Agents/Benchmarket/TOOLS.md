# Agent Tools Specification: Benchmarket

> **Authoritative Specification**: Tooling catalog, API endpoints, testing frameworks, and multi-language benchmark execution engines for `Benchmarket`.
> Unified persona consolidating quality engineering, test harness authoring, multi-language benchmarking (Python, Rust, JavaScript/TypeScript, Go, Java), and CLI performance instrumentation.

---

## Architecture: Benchmark & Verification Pipeline

```text
       [Inbound Task / Candidate Comparison]
                         │
                         ▼
             [Select Benchmark Harness]
   ┌─────────────┬─────────────┬─────────────┬─────────────┐
   │             │             │             │             │
   ▼             ▼             ▼             ▼             ▼
 Python        Rust        JS / TS          Go           Java
 pytest-bench  divan       mitata        testing.B       JMH
 pyperf        criterion   tinybench     benchstat    async-prof
 memray /      iai-        benchmark.js
 scalene       callgrind
   │             │             │             │             │
   └─────────────┴─────────────┼─────────────┴─────────────┘
                               ▼
                   [CLI System Benchmarking]
              hyperfine / oha / vegeta / wrk
                               │
                               ▼
               [Empirical Statistical Sampling]
              P50 / P95 / P99 Latency & Peak RSS RAM
                               │
                               ▼
               [Verification & Telemetry Ledger]
                  Benchmarks/telemetry.jsonl
```

---

## 1. Multi-Language Benchmark Libraries (2026 Reference)

### 1.1 Python Benchmark Ecosystem

| Library | Function | URL Documentation | Key Advantages |
| :--- | :--- | :--- | :--- |
| **`pytest-benchmark`** | Pytest-integrated statistical microbenchmarks | [pytest-benchmark Docs](https://pytest-benchmark.readthedocs.io/) | Native pytest fixtures, statistical outlier detection, regression threshold gating (`--benchmark-compare`), JSON export |
| **`pyperf`** | Isolated, tuned Python performance benchmarking | [pyperf Docs](https://pyperf.readthedocs.io/) | Process isolation, CPU affinity pinning, disabling Turbo Boost, cross-run delta comparison (`pyperf compare_to`) |
| **`memray`** | Memory allocation profiler (Python + C/C++) | [Memray Docs](https://bloomberg.github.io/memray/) | High-resolution heap profiling, flamegraph generation (`memray flamegraph`), live terminal view, leak detection |
| **`scalene`** | CPU, GPU, and memory profiler | [Scalene Repo](https://github.com/plasma-umass/scalene) | Disaggregates Python vs native C execution time, memory leak detection, line-level attribution |
| **`asv` (Airspeed Velocity)**| Git commit history performance tracking | [asv Docs](https://asv.readthedocs.io/) | Automated regression tracking across commits, interactive web dashboards |
| **`timeit`** | Standard library microbenchmarking | [timeit Python Docs](https://docs.python.org/3/library/timeit.html) | Zero dependencies, instant verification of small expressions |

#### Python Implementation Example (`pytest-benchmark` & `pyperf`)

```python
# test_vector_bench.py
import pytest
from swarm_sdk.memory.opencl_store import OpenClVecStore

def test_vector_similarity_benchmark(benchmark):
    store = OpenClVecStore(dim=64)
    query_vec = [0.15] * 64
    store.add("doc1", query_vec)

    # Statistical benchmark fixture
    result = benchmark.pedantic(
        store.query,
        args=(query_vec, 1),
        rounds=100,
        iterations=10,
    )
    assert len(result) == 1
```

```bash
# Run pytest-benchmark with JSON export and histogram
uv run pytest test_vector_bench.py --benchmark-json=bench_output.json --benchmark-histogram=bench_hist

# Run pyperf with CPU tuning and multi-process runs
uv run python -m pyperf timeit --tune --values=10 -s 'import math' 'math.sqrt(144)' -o baseline.json
```

---

### 1.2 Rust Benchmark Ecosystem

| Library | Function | URL Documentation | Key Advantages |
| :--- | :--- | :--- | :--- |
| **`divan`** | Next-generation fast Rust benchmark harness (2025–2026) | [Divan Repo](https://github.com/nvzqz/divan) / [Docs.rs](https://docs.rs/divan) | Zero-cost setup, generic parameter sweeps (`types = [u32, u64]`), built-in memory allocation counts, sub-nanosecond precision |
| **`criterion.rs`** | Statistics-driven microbenchmarking | [Criterion.rs Book](https://bheisler.github.io/criterion.rs/book/) | Bootstrap confidence intervals, regression detection against baselines, interactive HTML reports |
| **`iai-callgrind`** | Deterministic CPU instruction count benchmarks | [iai-callgrind Repo](https://github.com/iai-callgrind/iai-callgrind) | Runs on Valgrind Callgrind; measures instruction counts, cache misses, heap usage; completely immune to system noise |
| **`cargo-flamegraph`**| Stack trace sampling flamegraphs | [cargo-flamegraph Repo](https://github.com/flamegraph-rs/flamegraph) | Generates SVG flamegraphs directly from cargo test/bench via dtrace or perf |

#### Rust Implementation Example (`divan` & `criterion`)

```toml
# Cargo.toml
[dev-dependencies]
divan = "0.1"
criterion = { version = "0.5", features = ["html_reports"] }

[[bench]]
name = "compute_bench"
harness = false
```

```rust
// benches/compute_bench.rs (Divan)
use divan::{black_box, Bencher};

fn main() {
    divan::main();
}

#[divan::bench(args = [100, 1_000, 10_000])]
fn bench_hash_calculation(bencher: Bencher, n: usize) {
    bencher.bench_local(|| {
        let mut acc = 0u64;
        for i in 0..black_box(n) {
            acc = acc.wrapping_add(i as u64);
        }
        acc
    });
}
```

```bash
# Execute divan benchmark with allocation profiling
cargo bench --bench compute_bench

# Generate flamegraph
cargo flamegraph --bench compute_bench
```

---

### 1.3 JavaScript & TypeScript Benchmark Ecosystem

| Library | Function | URL Documentation | Key Advantages |
| :--- | :--- | :--- | :--- |
| **`mitata`** | High-performance micro-benchmarking for JS/TS/Bun/Node | [mitata Repo](https://github.com/evanwashere/mitata) | Sub-nanosecond resolution, JIT warmups, GC allocation tracking, clean terminal ASCII visualizations |
| **`tinybench`** | Minimalist zero-dependency modern benchmark library | [tinybench Repo](https://github.com/tinylibs/tinybench) | Node.js, Bun, Deno, and browser support, async task support, percentiles (p75, p95, p99, p99.9) |
| **`benchmark.js`** | Established statistical benchmarking engine | [Benchmark.js Website](https://benchmarkjs.com/) | Robust statistical confidence intervals, widespread adoption |

#### JavaScript / TypeScript Implementation Example (`mitata`)

```typescript
// bench.ts
import { bench, baseline, group, run } from 'mitata';

group('String Serialization', () => {
  baseline('JSON.stringify', () => {
    JSON.stringify({ id: 101, name: 'Benchmarket', active: true });
  });

  bench('Manual String Concat', () => {
    const id = 101;
    const name = 'Benchmarket';
    const active = true;
    `{"id":${id},"name":"${name}","active":${active}}`;
  });
});

await run({
  percentiles: true,
  avg: true,
  colors: true,
});
```

```bash
# Execute via Bun or Node.js
bun run bench.ts
# or
node --loader ts-node/esm bench.ts
```

---

### 1.4 Go Benchmark Ecosystem

| Library | Function | URL Documentation | Key Advantages |
| :--- | :--- | :--- | :--- |
| **`testing.B`** | Go standard library benchmark harness | [testing.B Go Docs](https://pkg.go.dev/testing#B) | Standard library fixture, `b.ResetTimer()`, `b.ReportAllocs()`, parameter scaling |
| **`benchstat`** | Statistical comparison tool for Go benchmarks | [benchstat Tool Docs](https://pkg.go.dev/golang.org/x/perf/cmd/benchstat) | Calculates delta percentages ($\Delta\%$), confidence intervals, and p-values using Mann-Whitney U test |

#### Go Implementation Example (`testing.B` & `benchstat`)

```go
// search_test.go
package search

import (
	"testing"
)

func BenchmarkLinearSearch(b *testing.B) {
	data := make([]int, 10000)
	target := 9999
	b.ResetTimer()
	b.ReportAllocs()

	for i := 0; i < b.N; i++ {
		for _, v := range data {
			if v == target {
				break
			}
		}
	}
}
```

```bash
# Run benchmark 10 times to capture statistical distribution
go test -bench=BenchmarkLinearSearch -benchmem -count=10 > old.txt

# Run candidate implementation
go test -bench=BenchmarkLinearSearch -benchmem -count=10 > new.txt

# Statistically compare baselines with p-values
benchstat old.txt new.txt
```

---

### 1.5 Java Benchmark Ecosystem

| Library | Function | URL Documentation | Key Advantages |
| :--- | :--- | :--- | :--- |
| **`JMH`** | OpenJDK Java Microbenchmark Harness | [JMH Project Repo](https://github.com/openjdk/jmh) | Avoids JVM JIT pitfalls (dead code elimination, loop unrolling), `Blackhole` consumers, warmup forks |
| **`async-profiler`** | Low-overhead Java sampling profiler | [async-profiler Repo](https://github.com/async-profiler/async-profiler) | Immune to JVM Safepoint bias; profiles CPU, heap allocations, lock contention, and generates flamegraphs |

#### Java Implementation Example (`JMH`)

```java
// MathBenchmark.java
package org.sample;

import org.openjdk.jmh.annotations.*;
import org.openjdk.jmh.infra.Blackhole;
import java.util.concurrent.TimeUnit;

@BenchmarkMode(Mode.AverageTime)
@OutputTimeUnit(TimeUnit.NANOSECONDS)
@Warmup(iterations = 3, time = 1, timeUnit = TimeUnit.SECONDS)
@Measurement(iterations = 5, time = 1, timeUnit = TimeUnit.SECONDS)
@Fork(1)
@State(Scope.Thread)
public class MathBenchmark {

    private double value = 144.0;

    @Benchmark
    public void testSquareRoot(Blackhole bh) {
        bh.consume(Math.sqrt(value));
    }
}
```

```bash
# Build and execute JMH harness
mvn clean install
java -jar target/benchmarks.jar -wi 3 -i 5 -f 1
```

---

## 2. CLI Benchmark & Profiler Tools (`CLITOOLS.md` Catalog)

Referenced directly from `~/Desktop/Documentos/CLITOOLS.md` (§10.2 Benchmarkers & §11 Profilers).

| Tool | Score | Function | Primary Documentation | Recommended Operational Command |
| :--- | :---: | :--- | :--- | :--- |
| **`hyperfine`** | **10** | Statistical command-line benchmark with warmup and distribution | [hyperfine GitHub](https://github.com/sharkdp/hyperfine) | `hyperfine --warmup 3 --runs 10 'cmd1' 'cmd2' --export-markdown report.md` |
| **`oha`** | **9** | Terminal HTTP load generator and latency histogram | [oha GitHub](https://github.com/hatoo/oha) | `oha -n 10000 -c 50 --latency-correction -z 30s http://localhost:8080/health` |
| **`py-spy`** | **9** | Zero-instrumentation Python sampling profiler | [py-spy GitHub](https://github.com/benfred/py-spy) | `py-spy record -o profile.svg --pid <PID>` or `py-spy top -- python app.py` |
| **`vegeta`** | **8** | Constant-rate HTTP load testing (avoids coordinated omission) | [vegeta GitHub](https://github.com/tsenart/vegeta) | `echo "GET http://localhost:8080" \| vegeta attack -rate=500/s -duration=30s \| vegeta report` |
| **`wrk`** | **6** | Multithreaded HTTP benchmarking tool with Lua scripts | [wrk GitHub](https://github.com/wg/wrk) | `wrk -t4 -c100 -d30s --latency http://localhost:8080/api` |
| **`samply`** | **10** | Low-overhead sampling profiler (Firefox Profiler UI) | [samply GitHub](https://github.com/mstange/samply) | `samply record ./target/release/my_binary` |

---

## 3. Operational Usage Recipes

### 3.1 Multi-Candidate Command Comparison (`hyperfine`)

```bash
# Compare two parser implementations with warmup runs and statistical exports
hyperfine \
  --warmup 3 \
  --runs 15 \
  --export-markdown candidate_delta.md \
  --export-json candidate_delta.json \
  'ast-grep outline --json=compact myfile.py' \
  'difft --dump-ts myfile.py'

# Parameter sweep across worker thread counts
hyperfine \
  --warmup 2 \
  -L threads 1,2,4,8,12 \
  'uv run python -m swarm_sdk.worker --threads {threads}'
```

### 3.2 High-Throughput HTTP Stress & Latency Gating (`oha`)

```bash
# Benchmark local API gateway with 50 concurrent connections over 30s
oha \
  -n 5000 \
  -c 50 \
  --latency-correction \
  --json \
  http://127.0.0.1:8000/api/v1/health > oha_results.json
```

### 3.3 Non-Invasive Python Profiling (`py-spy` & `memray`)

```bash
# Profile running swarm agent process without restarting
py-spy top --pid $(pgrep -f "swarm_sdk.orchestrator")

# Record full call stack flamegraph with native C extension frames
py-spy record -o memory_flamegraph.svg --native --pid $(pgrep -f "swarm_sdk")

# Track peak heap allocations with memray
uv run memray run -o mem_dump.bin my_script.py
uv run memray flamegraph mem_dump.bin
```

---

## 4. CLI Tool Provisioning & Installation Delegation Workflow (Compilator + ShellMaster)

`Benchmarket` focuses strictly on quality engineering, test harness authoring, and empirical performance benchmarking. When a required CLI benchmarking or profiling utility is absent from the host system or requires specialized compiler tuning, `Benchmarket` delegates tool installation through specialized swarm agents:

```text
       [Benchmarket: Check Tool in PATH]
                      │
         ┌────────────┴────────────┐
         ▼                         ▼
   Tool Available?           Tool Missing / Needs Optimization?
         │                         │
         │                         ├─ Pre-built package / shell PATH
         │                         │  └──► Task ShellMaster (brew, cargo, uv, pixi)
         │                         │
         │                         └─ From-source / native flags (-march=native, ThinLTO)
         │                            └──► Task Compilator (LLVM/Clang, toolchain.md)
         ▼                                 │
   Run Benchmark ◄─────────────────────────┘
```

### 4.1 Delegation Matrix

| Tool Requirement | Target Agent | Primary Execution Protocol | Example Tasks & Tools |
| :--- | :--- | :--- | :--- |
| **Pre-built CLI binaries** | **`ShellMaster`** | System package manager installation (`brew`, `cargo`, `pixi`, `uv`), environment setup, and PATH export | `brew install hyperfine oha wrk vegeta`<br>`cargo install samply`<br>`uv tool install py-spy` |
| **From-source compilation** | **`Compilator`** | Source build with host compiler optimization flags per `Toolchain.md` (`-O3 -march=native -mtune=native`, ThinLTO, Polly) | Compiling `wrk` with kqueue optimizations<br>Building custom Callgrind/Valgrind extensions<br>Resolving Mach-O / CLT link flags |
| **Python profilers & venvs** | **`ShellMaster`** | Python environment package provisioning via `uv` or `pip` | `uv pip install pytest-benchmark pyperf memray scalene` |
| **Rust benchmark dependencies** | **`Compilator`** | Toolchain pinning and Cargo workspace profiles | Adding `divan` or `criterion` to `Cargo.toml` with release profile optimization |

### 4.2 Inter-Agent Handoff Schema

When tasking `ShellMaster` or `Compilator`, `Benchmarket` emits a structured handoff payload:

```json
{
  "sender": "Benchmarket",
  "recipient": "ShellMaster",
  "task": "install_cli_tools",
  "payload": {
    "tools": ["hyperfine", "oha"],
    "manager_preference": ["brew", "cargo"],
    "required_by": "bench_api_gateway",
    "verification_command": "hyperfine --version && oha --version"
  }
}
```

```json
{
  "sender": "Benchmarket",
  "recipient": "Compilator",
  "task": "build_native_tool",
  "payload": {
    "tool": "wrk",
    "source_url": "https://github.com/wg/wrk",
    "optimization_flags": ["-O3", "-march=native", "-mtune=native"],
    "verification_command": "wrk --version"
  }
}
```

---

## 5. Telemetry Logging Contract

`Benchmarket` records every benchmark run into `Benchmarks/telemetry.jsonl` adhering to the following schema:

```json
{
  "timestamp": "2026-10-14T11:20:00Z",
  "agent": "Benchmarket",
  "task_id": "compare_candidates",
  "workload": "vector_similarity_search_10k",
  "hardware": {
    "cpu": "Intel Core i7-9750H (6c/12t)",
    "ram_gb": 16,
    "os": "macOS 26.7 x86_64"
  },
  "metrics": {
    "baseline_p50_ms": 1.42,
    "candidate_p50_ms": 0.88,
    "delta_percentage": -38.03,
    "throughput_ops_sec": 1136.36,
    "peak_rss_mb": 42.15,
    "allocations_count": 12400
  },
  "status": "pass",
  "verdict": "Candidate demonstrated 38.03% latency improvement within noise floor bounds."
}
```
