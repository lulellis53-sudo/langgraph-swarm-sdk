# Agent guidelines — LangGraph Swarm SDK

## Summary

Instructions for humans and AI assistants working in this repository. Read this first; drill into specialist docs only when your task requires them.

| Topic                                                     | What you will find                                                               |
| --------------------------------------------------------- | -------------------------------------------------------------------------------- |
| [Project overview](#topic-project-overview)               | What LangGraph Swarm SDK is; coding assistant vs swarm specialists               |
| [Repository layout](#topic-repository-layout)             | Path map; protobuf note; quick links                                             |
| [Development environment](#topic-development-environment) | Python/uv, services, quality gate, Colab/Codex, extensions                       |
| [Workflow](#topic-workflow)                               | How to change code; when stuck                                                   |
| [Benchmarks](#topic-benchmarks)                           | Task layout; SQL Pro suite                                                       |
| [Security and compliance](#topic-security-and-compliance) | Secrets; network exfiltration                                                    |
| [Git and documentation](#topic-git-and-documentation)     | Commits, README, dependencies                                                    |
| [Python Static Template](#topic-python-static-template)   | UNTOUCHABLE full scaffold + Python 3.15 app template; lite link; agent contract |

Human-oriented overview: `[README.md](README.md)`.

---

## Topic: Project overview

### Subtopic: What this project is

**LangGraph Swarm SDK** — a Python library and runtime for parallel multi-LLM swarms: LangGraph handoffs, semantic cache, hybrid retrieval, reranking, token budgets, and optional HTTP/gRPC APIs. The design goal is **fewer tokens** and **more relevant context**, not maximal model verbosity.

### Subtopic: Two kinds of “agents”

1. **Coding assistant (you in Cursor)** — edits this repo, runs tests, opens PRs. Follow the sections below.
2. **Swarm specialists (**`Agents/`***)** — fictional roles (Coder, Tester, Security, …) with JSON output contracts for orchestrated tasks. When emulating a role, read that folder’s `[AGENTS.md](Agents/Coder/AGENTS.md)` and obey its contract. When doing general repo work, use this file and the Coder-style norms (minimal diff, tests, no secrets).

For swarm coordination: start from `[Agents/SKILLS.md](Agents/SKILLS.md)` and `[Agents/coordination.yaml](Agents/coordination.yaml)`.

---

## Topic: Repository layout

### Subtopic: Repository map

| Path                                                         | Purpose                                                                                                  |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| `[src/swarm_sdk/](src/swarm_sdk/)`                           | Library: swarm runtime, cache, memory, routing, API/gRPC                                                 |
| `[src/swarm_sdk/orchestrator/](src/swarm_sdk/orchestrator/)` | Parallel plan engine: `spawn` (goal → structured plan) + `run_plan` (LangGraph dependency waves)          |
| `[src/swarm_sdk/serving/](src/swarm_sdk/serving/)`           | HTTP/gRPC/peer serving and LangGraph Server graph factories (`swarm`, `plan`)                              |
| `[src/swarm_sdk/serving/client.py](src/swarm_sdk/serving/client.py)` | `langgraph_sdk` client; `SWARM_SERVER_URL` delegates runs to a LangGraph Server                    |
| `[langgraph.json](langgraph.json)`                           | LangGraph Server manifest mapping the `swarm` and `plan` graph ids to factory functions                   |
| `[src/swarm_sdk/pb/](src/swarm_sdk/pb/)`                     | gRPC: `swarm.proto` + generated `swarm_pb2*` stubs                                                       |
| `[Main/config/swarm.yaml](Main/config/swarm.yaml)`           | Provider registry, routes, defaults (`SWARM_*` env overrides)                                            |
| `[Main/](Main/)`                                             | Embeddings/vectorstore re-exports, YAML, Essentials                                                      |
| `[WebSearch/](WebSearch/)`                                   | Search/scrape package (`frontend/` → `midend/` → `backend/`); see `[WebSearch/README.md](WebSearch/README.md)` |
| `[Agents/](Agents/)`                                         | Specialist **swarm personas** (`AGENTS.md` + `agent.yaml` per role)                                      |
| `[Agents/coordination.yaml](Agents/coordination.yaml)`       | Task graph for multi-agent workflows                                                                     |
| `[Agents/SKILLS.md](Agents/SKILLS.md)`                       | Specialist catalog: persona → handoff node/plan-worker wiring, how to add a specialist                    |
| `[Agents/benchmark/](Agents/benchmark/)`                     | Token/retrieval/swarm benchmarks; unit/integration tests in `[Agents/benchmark/tests/](Agents/benchmark/tests/)` (incl. `[Agents/benchmark/sql_pro/](Agents/benchmark/sql_pro/)`)  |
| `[.cursor/commands/](.cursor/commands/)`                     | Cursor slash commands (e.g. `/sql-pro`)                                                                  |
| `[.cursor/AGENTS.md](.cursor/AGENTS.md)`                     | Cursor agent guidelines, folder design, modus operandi                                                   |
| `[.cursor/rules/](.cursor/rules/)`                           | Project `.mdc` rules (core, Context7-after-edit, Python, protobuf, …)                                    |
| `[.cursor/templates/](.cursor/templates/)`                   | Static scaffolds — `[python_static_template_lite.py](.cursor/templates/python_static_template_lite.py)` or full `[python_static_template.py](.cursor/templates/python_static_template.py)` |
| `[.vscode/](.vscode/)`                                       | Workspace settings + extension recommendations (Cursor/VS Code)                                          |
| `[.cursor/extensions.txt](.cursor/extensions.txt)`           | Install list mirroring recommended extensions                                                            |
| `[.codex/config.toml](.codex/config.toml)`                   | Codex IDE/CLI defaults for this repo (`file_opener = cursor`)                                            |

Edit `[src/swarm_sdk/pb/swarm.proto](src/swarm_sdk/pb/swarm.proto)` then `uv run python -m swarm_sdk.pb` to regenerate stubs. Never commit `.env`.

### Subtopic: Quick links

- Agent index: `[Agents/SKILLS.md](Agents/SKILLS.md)`
- Workspace layout: `[codeworkspace/swarm.code-workspace](codeworkspace/swarm.code-workspace)`
- Benchmarks: `[Agents/benchmark/README.md](Agents/benchmark/README.md)`
- Toolchains and CPython support: `[Toolchain.md](Toolchain.md)`
- Static template: [@.cursor/templates/python_static_template.py](.cursor/templates/python_static_template.py)

---

## Topic: Development environment

### Subtopic: Python and uv

- **Python:** `>=3.14.5`, managed with **[uv](https://docs.astral.sh/uv/)**.
- **Install:** `uv sync --extra dev` (add `--extra faiss`, `--extra faiss-gpu`, `--extra embed`, `--extra molten`, `--extra observability`, `--extra qdrant`, `--extra mem0`, `--extra jupyter` as needed).

Use `uv run …` so commands use the project virtualenv.

### Subtopic: Services

- **Run services:** `uv run swarm-api`, `uv run swarm-grpc`.
- **LangGraph Server:** `[langgraph.json](langgraph.json)` serves the `swarm` (handoff graph) and `plan` (spawn → wave engine) graphs; factories in `[src/swarm_sdk/serving/graphs.py](src/swarm_sdk/serving/graphs.py)`. Deploy with `langgraph up` (the pinned `langgraph-cli` for Python 3.14 has no in-memory `dev` server), then call it with `SWARM_SERVER_URL=http://127.0.0.1:2024` — `SwarmSDK.run` delegates to the server via `langgraph_sdk` (`swarm_sdk.serving.client`). `swarm-api`/`swarm-grpc` remain the in-process serving paths.

### Subtopic: Quality gate

Run before claiming work is done:

```bash
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 pytest Agents/benchmark -q
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ruff check src Agents/benchmark Main
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ty check src Agents/benchmark Main
uv run python -m swarm_sdk.agents.validate
```

### Subtopic: Colab and Codex

- **Colab** (`google.colab`): open a `.ipynb` → **Select Kernel** → **Colab** → sign in with Google. Requires `uv sync --extra jupyter` for local kernels; Colab runs remotely.
- **Codex** (`openai.chatgpt`): open the Codex sidebar and sign in with ChatGPT. Repo defaults: `[.codex/config.toml](.codex/config.toml)`. For LangChain Codex routes, set `CODEX_OAUTH_TOKEN` in `.env` (see `[Main/config/model_registry.yaml](Main/config/model_registry.yaml)`).

### Subtopic: Editor extensions

- Cursor/VS Code will prompt from `[.vscode/extensions.json](.vscode/extensions.json)`, or `xargs -n1 code --install-extension < .cursor/extensions.txt`.

### Subtopic: Cursor IDE usage

Custom subagents live in `[.cursor/agents/](.cursor/agents/)` ([Cursor subagents](https://cursor.com/docs/subagents)). Slash commands live in `[.cursor/commands/](.cursor/commands/)`.

| In the Agent chat | What runs |
| ----------------- | --------- |
| `/worktree-websearch` | Slash command `[.cursor/commands/worktree-websearch.md](.cursor/commands/worktree-websearch.md)` — live research; does not patch the Hatch package |
| `/code-fixer` | Slash command `[.cursor/commands/code-fixer.md](.cursor/commands/code-fixer.md)` — apply the latest Reviewer / code-reviewer findings |
| `@code-fixer` or “send CodeFixer” | Subagent `[.cursor/agents/code-fixer.md](.cursor/agents/code-fixer.md)` (`name: code-fixer`) |
| `@WebSearch` then send Code Reviewer | Built-in `code-reviewer`; then `/code-fixer` to patch **critical** / **major** |

1. Open **Agent** (Cursor chat, Agent mode — not plain Ask).
2. Attach context with `@` (`@WebSearch`, a diff, or the review table).
3. Type `/code-fixer` or `@code-fixer`. The fixer inherits the parent model, edits claimed files, and runs focused tests. It does not commit unless you ask.

Also available in **Cursor CLI** and Cloud Agents. Swarm persona `Agents/CodeFixer/` is for plan workers, not this IDE subagent.

---

## Topic: Workflow

### Subtopic: How to change code

1. **Read first** — callers, tests, and config that touch the same behavior.
2. **Smallest correct diff** — no drive-by refactors, new abstractions, or dependencies unless the task requires them.
3. **Match conventions** — Ruff (`line-length = 100`, py314), existing naming and patterns in `src/swarm_sdk/`.
4. **Prove it** — failing test → fix → full [quality gate](#subtopic-quality-gate). Do not weaken lint/type checks without a named rule and reason.
5. **Config** — prefer `[Main/config/swarm.yaml](Main/config/swarm.yaml)` and agent manifests under `Agents/*/agent.yaml`; document new env vars in README or agent docs.
6. **Protobuf** — edit `[src/swarm_sdk/pb/swarm.proto](src/swarm_sdk/pb/swarm.proto)`, then regenerate with `uv run python -m swarm_sdk.pb`. Do not hand-edit `swarm_pb2`* stubs.
7. **New Python modules** — lite or full template (see [Python Static Template](#topic-python-static-template)); always `from __future__ import annotations` first.

### Subtopic: When stuck

- Report `blocked` with the exact command output after one reasonable retry.
- Prefer fixing the environment (uv sync, missing extra) over skipping tests.
- For provider/model behavior, read `[Main/config/swarm.yaml](Main/config/swarm.yaml)` and `[src/swarm_sdk/model_select.py](src/swarm_sdk/model_select.py)`.

---

## Topic: Benchmarks

### Subtopic: Benchmark layout

- Benchmark tasks live under `[Agents/benchmark/Tasks/](Agents/benchmark/Tasks/)`; results go to `Agents/benchmark/results/` (gitignored).

### Subtopic: SQL Pro

- SQL Pro suite: `[Agents/benchmark/sql_pro/suite.yaml](Agents/benchmark/sql_pro/suite.yaml)`, CLI `uv run python -m benchmark.sql_pro.run`, Cursor command `[.cursor/commands/sql-pro.md](.cursor/commands/sql-pro.md)`.

---

## Topic: Security and compliance

### Subtopic: Secrets

- Never commit `.env`, API keys, tokens, or credentials.
- Secrets live only in the macOS Keychain (`uv run swarm-vault set NAME`) or the gitignored, owner-only `.env` (`chmod 600`). Never add sudo, group or world read access to it.
- YAML (`agent.yaml`, `model_registry.yaml`, `coordination.yaml`, `swarm.yaml`) holds env-var **names** only (`api_key_env: ZAI_API_KEY`), never values. `test_yaml_never_holds_secret_values` enforces this; keep it green.
- Never paste secret values into issues, logs, or agent output (report path/pattern only — see `[Agents/Security/AGENTS.md](Agents/Security/AGENTS.md)`).

### Subtopic: Network

- Do not add network calls that exfiltrate repo data unless the user explicitly asks.

---

## Topic: Git and documentation

### Subtopic: Commits

- **Commits:** only when the user asks; do not force-push `main`.

### Subtopic: Documentation

- **Docs:** update `[README.md](README.md)` when behavior or install steps change; keep agent-specific rules in `Agents/*/AGENTS.md`.

### Subtopic: Dependencies

- **Dependencies:** add via `pyproject.toml` / `uv lock`; respect `[tool.uv]` constraints (e.g. `cryptography` wheel-only for Jupyter extra).

---

## Topic: Python Static Template #DO NOT TOUCH

```python
#!/usr/bin/env python3.15
"""Typed Python 3.15 application template using regular classes."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any, Protocol, TypeVar

lazy import numpy as np

T = TypeVar("T")
R = TypeVar("R")
LOGGER = logging.getLogger("app")
DEFAULTS = frozendict({"batch_size": 100, "multiplier": 1.0, "format": "auto"})
MISSING = sentinel("MISSING", module=__name__)


# ============================================================================
# DECORATORS
# ============================================================================

def timed(function: Callable[..., R]) -> Callable[..., R]:
    """Measure and log function runtime.

    Args:
        function: Callable to wrap.

    Returns:
        Wrapped callable.
    """

    def wrapper(*args: Any, **kwargs: Any) -> R:
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - started
            LOGGER.debug("%s completed in %.4fs", function.__name__, elapsed)

    return wrapper


# ============================================================================
# CONFIGURATION TYPE
# ============================================================================

class AppConfig:
    """Validated runtime configuration.

    Args:
        input_path: CSV or JSON source file.
        database_path: SQLite database destination.
        input_format: csv, json, or auto.
        batch_size: Number of rows per batch.
        multiplier: Positive numeric multiplier.
        dry_run: Skip database writes when True.
        verbose: Enable DEBUG logging when True.
    """

    def __init__(
        self,
        input_path: Path,
        database_path: Path,
        input_format: str = "auto",
        batch_size: int = 100,
        multiplier: float = 1.0,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> None:
        self.input_path = input_path
        self.database_path = database_path
        self.input_format = input_format
        self.batch_size = batch_size
        self.multiplier = multiplier
        self.dry_run = dry_run
        self.verbose = verbose

    def to_dict(self) -> dict[str, Any]:
        """Return the configuration as a dictionary."""
        return {
            "input_path": str(self.input_path),
            "database_path": str(self.database_path),
            "input_format": self.input_format,
            "batch_size": self.batch_size,
            "multiplier": self.multiplier,
            "dry_run": self.dry_run,
            "verbose": self.verbose,
        }


class Record:
    """Normalized application record.

    Args:
        identifier: Unique row identifier.
        name: Human-readable label.
        value: Original numeric value.
        score: Computed score.
    """

    def __init__(
        self,
        identifier: str,
        name: str,
        value: float,
        score: float = 0.0,
    ) -> None:
        self.identifier = identifier
        self.name = name
        self.value = value
        self.score = score

    def to_row(self) -> tuple[str, str, float, float]:
        """Return the record in SQLite parameter order."""
        return (self.identifier, self.name, self.value, self.score)

    def to_dict(self) -> dict[str, Any]:
        """Return the record as a serializable dictionary."""
        return {
            "identifier": self.identifier,
            "name": self.name,
            "value": self.value,
            "score": self.score,
        }


class RunResult:
    """Aggregate summary of a completed application run."""

    def __init__(
        self,
        total_rows: int,
        valid_rows: int,
        invalid_rows: int,
        saved_rows: int,
        elapsed_seconds: float,
    ) -> None:
        self.total_rows = total_rows
        self.valid_rows = valid_rows
        self.invalid_rows = invalid_rows
        self.saved_rows = saved_rows
        self.elapsed_seconds = elapsed_seconds

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable run summary."""
        return {
            "total_rows": self.total_rows,
            "valid_rows": self.valid_rows,
            "invalid_rows": self.invalid_rows,
            "saved_rows": self.saved_rows,
            "elapsed_seconds": self.elapsed_seconds,
        }


# ============================================================================
# PROTOCOLS BY TYPE
# ============================================================================

class RecordParser(Protocol):
    """Protocol for source parsers."""

    def parse(self, path: Path) -> Iterator[dict[str, Any]]:
        """Yield raw row dictionaries."""
        ...


class RecordRepository(Protocol):
    """Protocol for persistence implementations."""

    def initialize(self) -> None:
        """Prepare storage structures."""
        ...

    def upsert_many(self, records: Sequence[Record]) -> int:
        """Insert or update records and return row count."""
        ...


# ============================================================================
# VALIDATION TYPE
# ============================================================================

class RecordValidator:
    """Validate and normalize untrusted input rows."""

    REQUIRED_FIELDS = frozenset({"id", "name", "value"})

    @classmethod
    def normalize(cls, raw: dict[str, Any]) -> Record:
        """Convert one raw row into a validated Record.

        Args:
            raw: Untrusted row dictionary.

        Returns:
            Validated record.

        Raises:
            ValueError: If required values are missing or malformed.
        """
        missing = cls.REQUIRED_FIELDS - raw.keys()
        if missing:
            raise ValueError(f"Missing fields: {sorted(missing)}")

        identifier = str(raw.get("id", MISSING)).strip()
        name = str(raw.get("name", MISSING)).strip()

        if not identifier or identifier == str(MISSING):
            raise ValueError("Field 'id' cannot be blank")

        if not name or name == str(MISSING):
            raise ValueError("Field 'name' cannot be blank")

        try:
            value = float(raw["value"])
        except (TypeError, ValueError) as error:
            raise ValueError("Field 'value' must be numeric") from error

        return Record(identifier=identifier, name=name, value=value)


# ============================================================================
# MATH TYPES
# ============================================================================

class ScalarMath:
    """Scalar math functions for one value at a time."""

    @staticmethod
    def score(value: float, multiplier: float) -> float:
        """Return a rounded scalar score.

        Args:
            value: Input numeric value.
            multiplier: Positive scaling multiplier.

        Returns:
            Rounded score.

        Raises:
            ValueError: If multiplier is not positive.
        """
        if multiplier <= 0:
            raise ValueError("Multiplier must be greater than zero")

        return round(value * multiplier, 4)

    @classmethod
    def enrich_many(cls, records: Sequence[Record], multiplier: float) -> list[Record]:
        """Apply scalar math over a sequence of records."""
        return [
            Record(
                identifier=record.identifier,
                name=record.name,
                value=record.value,
                score=cls.score(record.value, multiplier),
            )
            for record in records
        ]


class VectorMath:
    """Vectorized math using NumPy arrays."""

    @staticmethod
    def enrich_many(records: Sequence[Record], multiplier: float) -> list[Record]:
        """Compute scores with vectorized array operations.

        Args:
            records: Input records.
            multiplier: Positive scaling multiplier.

        Returns:
            Enriched records with computed scores.
        """
        if multiplier <= 0:
            raise ValueError("Multiplier must be greater than zero")

        values = np.array([record.value for record in records], dtype=float)
        scores = np.round(values * multiplier, decimals=4)

        return [
            Record(
                identifier=record.identifier,
                name=record.name,
                value=record.value,
                score=float(score),
            )
            for record, score in zip(records, scores, strict=True)
        ]


# ============================================================================
# PARSER TYPES
# ============================================================================

class CsvParser:
    """CSV parser by header names."""

    @timed
    def parse(self, path: Path) -> Iterator[dict[str, Any]]:
        """Yield CSV rows as dictionaries."""
        with path.open("r", encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames is None:
                raise ValueError("CSV must contain a header row")
            for row in reader:
                yield dict(row)


class JsonParser:
    """JSON parser for a root list of objects."""

    @timed
    def parse(self, path: Path) -> Iterator[dict[str, Any]]:
        """Yield JSON objects from a root list."""
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)

        if not isinstance(payload, list):
            raise ValueError("JSON root must be a list")

        for index, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"JSON item {index} must be an object")
            yield item


class ParserFactory:
    """Factory that selects the parser type for an input file."""

    @staticmethod
    def create(input_format: str, path: Path) -> RecordParser:
        """Return a parser based on explicit format or file suffix."""
        resolved = path.suffix.lower().lstrip(".") if input_format == "auto" else input_format.lower()

        if resolved == "csv":
            return CsvParser()
        if resolved == "json":
            return JsonParser()

        raise ValueError("Unsupported format. Use csv, json, or auto.")


# ============================================================================
# DATABASE TYPE
# ============================================================================

class SqliteRepository:
    """SQLite repository with parameterized writes."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection."""
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @timed
    def initialize(self) -> None:
        """Create the records table if it does not exist."""
        statement = """
        CREATE TABLE IF NOT EXISTS records (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            value REAL NOT NULL,
            score REAL NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
        with self._connect() as connection:
            connection.execute(statement)

    @timed
    def upsert_many(self, records: Sequence[Record]) -> int:
        """Insert or update multiple records.

        Args:
            records: Validated and enriched records.

        Returns:
            Number of processed rows.
        """
        if not records:
            return 0

        statement = """
        INSERT INTO records (id, name, value, score)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            value = excluded.value,
            score = excluded.score,
            updated_at = CURRENT_TIMESTAMP
        """

        with self._connect() as connection:
            connection.executemany(statement, [record.to_row() for record in records])

        return len(records)


# ============================================================================
# FUNCTION TYPES
# ============================================================================

def batched(items: Iterable[T], batch_size: int) -> Iterator[list[T]]:
    """Yield items in fixed-size batches.

    Args:
        items: Source iterable.
        batch_size: Maximum items per batch.

    Yields:
        Lists of at most batch_size items.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least one")

    batch: list[T] = []
    for item in items:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []

    if batch:
        yield batch


def positive_int(value: str) -> int:
    """Parse a positive integer for argparse."""
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return result


def positive_float(value: str) -> float:
    """Parse a positive float for argparse."""
    result = float(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return result


def configure_logging(verbose: bool) -> None:
    """Configure stdlib logging."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(
        description="Typed CSV/JSON processing template using regular classes.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", required=True, type=Path, help="Path to CSV or JSON input file.")
    parser.add_argument("--database", type=Path, default=Path("app.db"), help="SQLite database destination.")
    parser.add_argument("--format", choices=("auto", "csv", "json"), default=DEFAULTS["format"], help="Input format.")
    parser.add_argument("--batch-size", type=positive_int, default=DEFAULTS["batch_size"], help="Rows per batch.")
    parser.add_argument("--multiplier", type=positive_float, default=DEFAULTS["multiplier"], help="Positive score multiplier.")
    parser.add_argument("--dry-run", action="store_true", help="Process input without writing to the database.")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG-level logging.")
    return parser


def parse_config(argv: Sequence[str] | None = None) -> AppConfig:
    """Parse command-line arguments into AppConfig."""
    args = build_parser().parse_args(argv)

    if not args.input.is_file():
        raise FileNotFoundError(f"Input file does not exist: {args.input}")

    return AppConfig(
        input_path=args.input,
        database_path=args.database,
        input_format=args.format,
        batch_size=args.batch_size,
        multiplier=args.multiplier,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


# ============================================================================
# APPLICATION TYPE
# ============================================================================

class Application:
    """Coordinate parsing, validation, math, loops, and persistence."""

    def __init__(
        self,
        config: AppConfig,
        parser: RecordParser,
        repository: RecordRepository,
    ) -> None:
        self.config = config
        self.parser = parser
        self.repository = repository

    @timed
    def run(self) -> RunResult:
        """Run the full processing pipeline."""
        started = time.perf_counter()

        if not self.config.dry_run:
            self.repository.initialize()

        total_rows = 0
        valid_rows = 0
        invalid_rows = 0
        saved_rows = 0

        for batch_number, raw_batch in enumerate(
            batched(self.parser.parse(self.config.input_path), self.config.batch_size),
            start=1,
        ):
            total_rows += len(raw_batch)
            normalized: list[Record] = []

            for row_number, raw in enumerate(raw_batch, start=1):
                try:
                    normalized.append(RecordValidator.normalize(raw))
                except ValueError as error:
                    invalid_rows += 1
                    LOGGER.warning(
                        "Rejected batch=%s row=%s error=%s",
                        batch_number,
                        row_number,
                        error,
                    )

            valid_rows += len(normalized)
            if not normalized:
                continue

            enriched = VectorMath.enrich_many(normalized, self.config.multiplier)

            if self.config.dry_run:
                LOGGER.info(
                    "Dry run batch=%s accepted=%s",
                    batch_number,
                    len(enriched),
                )
                continue

            saved_rows += self.repository.upsert_many(enriched)
            LOGGER.info(
                "Processed batch=%s received=%s accepted=%s saved=%s",
                batch_number,
                len(raw_batch),
                len(enriched),
                len(enriched),
            )

        elapsed_seconds = round(time.perf_counter() - started, 4)
        return RunResult(
            total_rows=total_rows,
            valid_rows=valid_rows,
            invalid_rows=invalid_rows,
            saved_rows=saved_rows,
            elapsed_seconds=elapsed_seconds,
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Application entry point."""
    try:
        config = parse_config(argv)
        configure_logging(config.verbose)

        parser = ParserFactory.create(config.input_format, config.input_path)
        repository = SqliteRepository(config.database_path)
        app = Application(config=config, parser=parser, repository=repository)

        print(json.dumps(app.run().to_dict(), indent=2))
        return 0

    except (FileNotFoundError, ValueError, sqlite3.Error) as error:
        LOGGER.error("%s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

### Subtopic: Mandatory first import

Module docstring, then immediately:

```python
from __future__ import annotations
```

### Subtopic: Agent contract

- Read callers, tests, and config before editing.
- One failed attempt → analyse → one deliberate fix (no blind retries).
- Profile before optimizing; use `SWARM_PROFILE=1` only for `@wrappers.timed` on non-hot paths.
- Parallel swarm steps: disjoint `files` per sibling; cap via `cowork_parallel_cap()` / `swarm_sdk.runtime.concurrency.parallel_cap`.
- Delete unused role sections when copying; no import-time side effects.

### Subtopic: When to use

| Scaffold | Use when |
| -------- | -------- |
| **lite** | New small module (types + cowork cap only) |
| **full** | Needs vect/math/db/batch roles |
| **3.15 app** | Standalone typed CLI (CSV/JSON → SQLite); UNTOUCHABLE block above |

Do **not** import template files from runtime package code — copy and trim.

### Subtopic: Roles at a glance (full template)

| Role | Class | Functions | Concern |
| ------ | -------- | ----------- | --------- |
| type | `TypeRole` | `type_*` | Protocols, narrowers |
| hint | `HintRole` | `hint_*` | Annotations / metadata |
| vect | `VectRole` | `vect_*` | Vectors / embeddings math |
| math | `MathRole` | `math_*` | Scalar / reductions (no I/O) |
| db | `DbRole` | `db_*` | Store / connection façade |
| batch | `BatchRole` | `batch_*`, `loop_*` | Bounded batch/async (`LoopRole` = alias) |
| cowork | `CoworkRole` | `cowork_*` | PEP 703 caps; runtime: `swarm_sdk.runtime.concurrency` |

### Subtopic: Wrappers

- `@wrappers.retry_transient(times=2, on=(TimeoutError, OSError, ConnectionError))` — not for logic bugs.
- `@wrappers.timed` — active only when `SWARM_PROFILE` is set.

### Subtopic: Smoke check

```bash
uv run python .cursor/templates/python_static_template.py
uv run python .cursor/templates/python_static_template_lite.py
```
