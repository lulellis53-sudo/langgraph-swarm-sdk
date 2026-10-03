"""Run SQL Pro benchmark cases against an in-memory SQLite database."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SUITE_ROOT = Path(__file__).parent
DEFAULT_SUITE = SUITE_ROOT / "suite.yaml"


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    latency_ms: float = 0.0
    row_count: int = 0
    explain_plan: str = ""
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "latency_ms": self.latency_ms,
            "row_count": self.row_count,
            "explain_plan": self.explain_plan,
            "notes": self.notes,
            "error": self.error,
        }


def load_suite(path: Path | None = None) -> dict[str, Any]:
    suite_path = path or DEFAULT_SUITE
    with suite_path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _apply_schema(conn: sqlite3.Connection) -> None:
    schema = (SUITE_ROOT / "fixtures" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)


def seed_default(conn: sqlite3.Connection, *, customers: int = 100, orders_per: int = 50) -> None:
    """Deterministic seed: 100 customers, 50 orders each, ~5 items per order."""
    conn.execute("DELETE FROM order_items")
    conn.execute("DELETE FROM orders")
    conn.execute("DELETE FROM customers")

    statuses = ("active", "completed", "cancelled")
    for cid in range(1, customers + 1):
        conn.execute(
            "INSERT INTO customers (customer_id, name, country, created_at) VALUES (?, ?, ?, ?)",
            (cid, f"Customer {cid}", "US" if cid % 3 else "CA", f"2024-01-{cid % 28 + 1:02d}"),
        )
        for n in range(orders_per):
            oid = (cid - 1) * orders_per + n + 1
            status = statuses[n % 3]
            month = (n % 12) + 1
            conn.execute(
                """
                INSERT INTO orders (order_id, customer_id, order_date, total, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (oid, cid, f"2024-{month:02d}-{(n % 27) + 1:02d}", float(10 + (oid % 97)), status),
            )
            for k in range(5):
                conn.execute(
                    "INSERT INTO order_items (order_item_id, order_id, quantity) VALUES (?, ?, ?)",
                    (oid * 10 + k, oid, 1 + (k % 4)),
                )
    conn.commit()


def explain_plan(conn: sqlite3.Connection, query: str) -> str:
    rows = conn.execute(f"EXPLAIN QUERY PLAN {query}").fetchall()
    return "\n".join(" | ".join(str(cell) for cell in row) for row in rows)


def fetch_all(conn: sqlite3.Connection, query: str) -> list[tuple[Any, ...]]:
    return conn.execute(query).fetchall()


def _seed(conn: sqlite3.Connection, name: str) -> None:
    if name == "default":
        seed_default(conn)
        return
    raise ValueError(f"unknown seed {name!r}")


def _run_timed(
    conn: sqlite3.Connection, query: str
) -> tuple[list[tuple[Any, ...]], float, list[str]]:
    start = time.perf_counter()
    cur = conn.execute(query)
    rows = cur.fetchall()
    columns = [str(col[0]) for col in cur.description] if cur.description else []
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return rows, elapsed_ms, columns


def _check_expect_columns(expect: dict[str, Any], columns: list[str], notes: list[str]) -> bool:
    expected = expect.get("columns")
    if expected is None:
        return True
    if columns != list(expected):
        notes.append(f"expected columns={expected!r}, got {columns!r}")
        return False
    return True


def _check_plan_tokens(plan: str, must_contain: list[Any], notes: list[str], *, label: str) -> bool:
    passed = True
    for token in must_contain:
        if str(token) not in plan:
            passed = False
            notes.append(f"{label} missing {token!r}")
    return passed


class SqlProSuite:
    def __init__(self, suite: dict[str, Any] | None = None) -> None:
        self.suite = suite or load_suite()
        self.cases: list[dict[str, Any]] = list(self.suite.get("cases", []))

    def _fresh_connection(self, seed: str = "default") -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        _apply_schema(conn)
        _seed(conn, seed)
        return conn

    def _case_seed(self, case: dict[str, Any]) -> str:
        return str(case.get("seed", "default"))

    def run_case(self, case: dict[str, Any]) -> CaseResult:
        case_id = str(case["id"])
        try:
            if "query_slow" in case and "query_fast" in case:
                return self._run_equivalence_case(case_id, case)
            if "index_ddl" in case:
                return self._run_index_case(case_id, case)
            return self._run_single_query_case(case_id, case)
        except ValueError as exc:
            return CaseResult(case_id=case_id, passed=False, error=str(exc))
        except sqlite3.Error as exc:
            return CaseResult(case_id=case_id, passed=False, error=str(exc))

    def _run_single_query_case(self, case_id: str, case: dict[str, Any]) -> CaseResult:
        conn = self._fresh_connection(self._case_seed(case))
        query = str(case["query"]).strip()
        rows, latency_ms, columns = _run_timed(conn, query)
        plan = explain_plan(conn, query)
        expect = case.get("expect", {})
        notes: list[str] = []
        passed = True

        if not _check_expect_columns(expect, columns, notes):
            passed = False

        if "row_count" in expect and len(rows) != int(expect["row_count"]):
            passed = False
            notes.append(f"expected row_count={expect['row_count']}, got {len(rows)}")

        if "min_rows" in expect and len(rows) < int(expect["min_rows"]):
            passed = False
            notes.append(f"expected min_rows={expect['min_rows']}, got {len(rows)}")

        for token in expect.get("plan_must_not_contain", []):
            if token in plan:
                passed = False
                notes.append(f"plan must not contain {token!r}")

        conn.close()
        return CaseResult(
            case_id=case_id,
            passed=passed,
            latency_ms=latency_ms,
            row_count=len(rows),
            explain_plan=plan,
            notes=notes,
        )

    def _run_equivalence_case(self, case_id: str, case: dict[str, Any]) -> CaseResult:
        slow_q = str(case["query_slow"]).strip()
        fast_q = str(case["query_fast"]).strip()

        seed = self._case_seed(case)
        conn_slow = self._fresh_connection(seed)
        slow_rows, slow_ms, _ = _run_timed(conn_slow, slow_q)
        conn_slow.close()

        conn_fast = self._fresh_connection(seed)
        fast_rows, fast_ms, _ = _run_timed(conn_fast, fast_q)
        plan = explain_plan(conn_fast, fast_q)
        conn_fast.close()

        expect = case.get("expect", {})
        passed = slow_rows == fast_rows
        notes: list[str] = []
        if not passed:
            notes.append("slow and fast queries returned different result sets")

        if expect.get("fast_faster_than_slow") and fast_ms >= slow_ms * 0.99:
            passed = False
            notes.append(
                f"expected fast faster than slow; slow_ms={slow_ms:.3f} fast_ms={fast_ms:.3f}"
            )

        return CaseResult(
            case_id=case_id,
            passed=passed,
            latency_ms=fast_ms,
            row_count=len(fast_rows),
            explain_plan=plan,
            notes=notes + [f"slow_ms={slow_ms:.3f}", f"fast_ms={fast_ms:.3f}"],
        )

    def _run_index_case(self, case_id: str, case: dict[str, Any]) -> CaseResult:
        query = str(case["query"]).strip()
        index_ddl = str(case["index_ddl"]).strip()
        expect = case.get("expect", {})

        seed = self._case_seed(case)
        conn_before = self._fresh_connection(seed)
        plan_before = explain_plan(conn_before, query)
        conn_before.close()

        conn_after = self._fresh_connection(seed)
        conn_after.executescript(index_ddl)
        conn_after.commit()
        rows, latency_ms, columns = _run_timed(conn_after, query)
        plan_after = explain_plan(conn_after, query)
        conn_after.close()

        passed = True
        notes = [f"plan_before:\n{plan_before}"]
        if not _check_plan_tokens(
            plan_before,
            expect.get("plan_before_index_must_contain", []),
            notes,
            label="plan before index",
        ):
            passed = False
        if not _check_plan_tokens(
            plan_after,
            expect.get("plan_after_index_must_contain", []),
            notes,
            label="plan after index",
        ):
            passed = False

        if not _check_expect_columns(expect, columns, notes):
            passed = False

        if "min_rows" in expect and len(rows) < int(expect["min_rows"]):
            passed = False
            notes.append(f"expected min_rows={expect['min_rows']}, got {len(rows)}")

        return CaseResult(
            case_id=case_id,
            passed=passed,
            latency_ms=latency_ms,
            row_count=len(rows),
            explain_plan=plan_after,
            notes=notes,
        )

    def run_all(self) -> list[CaseResult]:
        return [self.run_case(case) for case in self.cases]
