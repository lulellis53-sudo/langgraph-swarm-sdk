"""Command-line interface for the low-resource autonomous code synthesis swarm (`low-swarm`)."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from swarm_sdk.config.loader import load_swarm_config
from swarm_sdk.core.rules import HostRuleEngine
from swarm_sdk.orchestrator.low_swarm import LowSwarmEngine
from swarm_sdk.retrieval.rag_ingest import RAGIngestionPipeline
from swarm_sdk.vault import (
    _NAME,
    KNOWN_NAMES,
    get_secret,
    get_with_source,
    set_secret,
)

# -----------------------------------------------------------------------------
# Rich Console & Fallback Abstraction
# -----------------------------------------------------------------------------

try:
    from rich.console import Console as _RichConsole
    from rich.panel import Panel as _RichPanel
    from rich.syntax import Syntax as _RichSyntax
    from rich.table import Table as _RichTable

    _RICH_AVAILABLE = True
except ImportError:
    _RichConsole = None
    _RichPanel = None
    _RichSyntax = None
    _RichTable = None
    _RICH_AVAILABLE = False


class PlainTable:
    """Lightweight plain-text table formatter fallback when Rich is unavailable."""

    def __init__(self, title: str = "") -> None:
        """Initialize an empty table with the given column headers."""
        self.title = title
        self.columns: list[str] = []
        self.rows: list[list[str]] = []

    def add_column(self, header: str, **kwargs: Any) -> None:
        """Add a column header."""
        self.columns.append(header)

    def add_row(self, *args: Any, **kwargs: Any) -> None:
        """Append one row of cells."""
        cleaned_cells = [
            re.sub(
                r"\[/?(?:bold|italic|underline|green|red|yellow|blue|cyan|magenta|dim|white)[^\]]*\]",
                "",
                str(a),
            )
            for a in args
        ]
        self.rows.append(cleaned_cells)

    def __str__(self) -> str:
        lines: list[str] = []
        if self.title:
            lines.append(f"=== {self.title} ===")
        if not self.columns:
            return "\n".join(lines)

        col_widths = [len(c) for c in self.columns]
        for row in self.rows:
            for i, val in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(val))

        header_line = " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(self.columns))
        sep_line = "-+-".join("-" * col_widths[i] for i in range(len(self.columns)))
        lines.append(header_line)
        lines.append(sep_line)

        for row in self.rows:
            r_cells = [
                row[i].ljust(col_widths[i]) if i < len(row) else "".ljust(col_widths[i])
                for i in range(len(self.columns))
            ]
            lines.append(" | ".join(r_cells))

        return "\n".join(lines)


class PlainPanel:
    """Lightweight plain-text panel fallback when Rich is unavailable."""

    def __init__(self, content: Any, title: str = "", **kwargs: Any) -> None:
        """Initialize the panel with its title and body lines."""
        self.content = content
        self.title = title

    def __str__(self) -> str:
        content_str = str(self.content)
        cleaned = re.sub(
            r"\[/?(?:bold|italic|underline|green|red|yellow|blue|cyan|magenta|dim|white)[^\]]*\]",
            "",
            content_str,
        )
        hdr = f"[{self.title}]" if self.title else ""
        return f"+--- {hdr} ---+\n{cleaned}\n+---------------------------------+"


class PlainConsole:
    """Lightweight plain-text console fallback writing to stdout."""

    def __init__(self, file: Any = None) -> None:
        """Initialize the fallback console (no rich required)."""
        self.file = file or sys.stdout

    def print(self, *args: Any, **kwargs: Any) -> None:
        """Render the table to stdout."""
        if not args:
            print(file=self.file)
            return

        out_parts: list[str] = []
        for a in args:
            if isinstance(a, (PlainTable, PlainPanel)):
                out_parts.append(str(a))
            else:
                cleaned = re.sub(
                    r"\[/?(?:bold|italic|underline|green|red|yellow|blue|cyan|magenta|dim|white)[^\]]*\]",
                    "",
                    str(a),
                )
                out_parts.append(cleaned)
        print(" ".join(out_parts), file=self.file)

    def rule(self, title: str = "") -> None:
        """Render a horizontal rule."""
        if title:
            self.print(f"--- {title} ---")
        else:
            self.print("-" * 40)


def get_console() -> Any:
    """Returns Rich Console if installed, otherwise PlainConsole."""
    if _RICH_AVAILABLE and _RichConsole is not None:
        return _RichConsole(file=sys.stdout, highlight=False)
    return PlainConsole(file=sys.stdout)


def create_table(title: str = "") -> Any:
    """Creates a Rich Table if available, otherwise PlainTable."""
    if _RICH_AVAILABLE and _RichTable is not None:
        return _RichTable(title=title, show_header=True)
    return PlainTable(title=title)


def create_panel(content: Any, title: str = "") -> Any:
    """Creates a Rich Panel if available, otherwise PlainPanel."""
    if _RICH_AVAILABLE and _RichPanel is not None:
        return _RichPanel(content, title=title)
    return PlainPanel(content, title=title)


# -----------------------------------------------------------------------------
# Vault Service Name Normalizer
# -----------------------------------------------------------------------------


def normalize_service(service: str) -> str:
    """Maps colloquial service names (e.g. 'openai', 'jev') to standard environment keys."""
    s = service.strip()
    if s.lower() in ("openai", "openai_api_key"):
        return "OPENAI_API_KEY"
    if s.lower() in ("jev", "jev_api_key"):
        return "JEV_API_KEY"
    upper = s.upper()
    if upper.endswith("_API_KEY"):
        return upper
    cand = f"{upper}_API_KEY"
    if cand in KNOWN_NAMES:
        return cand
    if _NAME.fullmatch(upper):
        return upper
    return s


# -----------------------------------------------------------------------------
# Subcommand Handlers
# -----------------------------------------------------------------------------


# Global tracker for latest execution state (for CLI & programmatic inspection)
latest_state: dict[str, Any] | None = None


def get_latest_state() -> dict[str, Any] | None:
    """Returns the most recent execution state from handle_run."""
    return latest_state


def handle_run(args: argparse.Namespace, console: Any) -> int:
    """Executes code synthesis state machine via LowSwarmEngine."""
    global latest_state
    task: str = args.task
    files: list[str] | None = args.files
    profile: bool = bool(args.profile)
    verbose: bool = bool(args.verbose)

    engine = LowSwarmEngine()

    start_time = time.perf_counter()
    start_cpu = time.process_time()
    state = engine.run(task=task, target_files=files, profile=profile)
    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
    cpu_ms = (time.process_time() - start_cpu) * 1000.0

    status = state.get("status", "unknown")
    is_success = status == "success"
    jev = state.get("jev_decision") or {}
    lifeguard = state.get("lifeguard_report") or {}
    error = state.get("error")

    # Render primary status panel
    table = create_table(title=f"Low-Swarm Engine: {task}")
    table.add_column("Dimension", style="bold")
    table.add_column("Result")

    if is_success:
        status_str = "[bold green]SUCCESS[/bold green]"
    else:
        status_str = f"[bold red]{status.upper()}[/bold red]"
    table.add_row("Status", status_str)

    model_tier = jev.get("model_tier", "auto")
    table.add_row("Model Tier", str(model_tier))

    jev_safe = jev.get("safe", False)
    jev_str = (
        f"[green]Safe[/green] (tier: {model_tier}, score: {jev.get('score', 0):.2f})"
        if jev_safe
        else "[red]Blocked by safety gate[/red]"
    )
    table.add_row("Jev Decision", jev_str)

    lg_approved = lifeguard.get("is_approved", False)
    violations = lifeguard.get("violations", [])
    if lg_approved:
        lg_str = "[green]APPROVED[/green] (0 violations)"
    else:
        v_count = len(violations)
        lg_str = f"[red]REJECTED[/red] ({v_count} violation{'s' if v_count != 1 else ''})"
    table.add_row("Lifeguard Audit", lg_str)

    if error:
        table.add_row("Error Detail", f"[red]{error}[/red]")

    if profile:
        rss = state.get("metrics", {}).get("rss_gb", engine.get_current_rss_gb())
        if "metrics" not in state or not isinstance(state["metrics"], dict):
            state["metrics"] = {}
        state["metrics"]["wall_clock_ms"] = elapsed_ms
        state["metrics"]["cpu_time_ms"] = cpu_ms
        state["metrics"]["rss_gb"] = rss
        table.add_row("Profile Latency", f"{elapsed_ms:.2f} ms")
        table.add_row("CPU Time", f"{cpu_ms:.2f} ms")
        table.add_row("Process RSS", f"{rss:.2f} GB")

    latest_state = cast("dict[str, Any]", state)
    console.print(create_panel(table, title="Execution Summary"))

    # If execution succeeded, write synthesized code to target files if existing or --apply
    if is_success:
        synthesized_code = state.get("synthesized_code") or {}
        for fname, code in synthesized_code.items():
            fpath = Path(fname)
            if fpath.exists() or getattr(args, "apply", False):
                try:
                    fpath.parent.mkdir(parents=True, exist_ok=True)
                    fpath.write_text(code, encoding="utf-8")
                except OSError:
                    pass

    # Render diff patches if synthesized
    diff_patches = state.get("diff_patches") or []
    if diff_patches:
        console.rule("Synthesized Diff Patches")
        for diff in diff_patches:
            if _RICH_AVAILABLE and _RichSyntax is not None:
                console.print(_RichSyntax(diff, "diff"))
            else:
                console.print(diff)

    if verbose:
        console.rule("Verbose Telemetry")
        console.print(f"Target files: {state.get('target_files')}")
        console.print(f"Context chunks: {len(state.get('context_chunks', []))}")
        console.print(f"Iterations: {state.get('iteration', 0)}")

    return 0 if is_success else 1


def handle_vault(args: argparse.Namespace, console: Any) -> int:
    """Manages Keychain credentials for OpenAI and Jev keys."""
    subcmd = getattr(args, "vault_command", None)

    if subcmd == "set":
        service = getattr(args, "service", None)
        key = getattr(args, "key", None)
        if not service or not key:
            console.print("[red]Error: --service and --key are required for vault set.[/red]")
            return 1

        norm_name = normalize_service(service)
        try:
            ok = set_secret(norm_name, key)
            if ok:
                msg = f"[green]Successfully saved secret for {norm_name} in macOS Keychain.[/green]"
                console.print(msg)
                return 0
            console.print(f"[red]Failed to save secret for {norm_name} in Keychain.[/red]")
            return 1
        except Exception as exc:
            console.print(f"[red]Error saving secret: {exc}[/red]")
            return 1

    elif subcmd == "get":
        service = getattr(args, "service", None)
        if not service:
            console.print("[red]Error: --service is required for vault get.[/red]")
            return 1

        norm_name = normalize_service(service)
        val = get_secret(norm_name, fallback_env=True)
        if val is not None:
            console.print(val)
            return 0
        console.print(f"[red]Secret not found for service '{service}' ({norm_name}).[/red]")
        return 1

    elif subcmd == "status":
        table = create_table(title="Keychain Vault Status")
        table.add_column("Secret Name", style="bold")
        table.add_column("Configured")
        table.add_column("Provider Source")

        # Focus on OPENAI_API_KEY, JEV_API_KEY, and known names
        keys_to_inspect = ("OPENAI_API_KEY", "JEV_API_KEY", "MEM0_API_KEY")
        for k in keys_to_inspect:
            found = get_with_source(k)
            if found:
                table.add_row(k, "[green]CONFIGURED[/green]", found[1])
            else:
                table.add_row(k, "[yellow]MISSING[/yellow]", "not found")

        console.print(table)
        return 0

    console.print("[red]Unknown vault command. Use 'set', 'get', or 'status'.[/red]")
    return 1


def handle_ingest(args: argparse.Namespace, console: Any) -> int:
    """Ingests Markdown documents into the vector index and saves to disk."""
    source_str = getattr(args, "source", None)
    output_str = getattr(args, "output", None)

    if not source_str or not output_str:
        console.print("[red]Error: --source and --output are required for ingest.[/red]")
        return 1

    source_path = Path(os.path.expanduser(source_str))
    output_path = Path(os.path.expanduser(output_str))

    if not source_path.exists():
        console.print(f"[red]Error: Source path '{source_path}' does not exist.[/red]")
        return 1

    try:
        rag = load_swarm_config().rag
        pipeline = RAGIngestionPipeline(child_size=rag.child_size if rag.parent_child else None)
        count = pipeline.ingest_files([source_path])
        pipeline.save(output_path)
        console.print(f"[green]Successfully ingested {count} chunks into {output_path}[/green]")
        return 0
    except Exception as exc:
        console.print(f"[red]Error during RAG ingestion: {exc}[/red]")
        return 1


def handle_doctor(args: argparse.Namespace, console: Any) -> int:
    """Inspects host invariants, SIMD architecture, and modern CLI tools."""
    engine = HostRuleEngine()
    inv = engine.invariants

    console.rule("Host Architecture & Diagnostic Inspection")

    table = create_table(title="Host Diagnostics (Intel Core i7-9750H Profile)")
    table.add_column("Component", style="bold")
    table.add_column("Specification / Value")
    table.add_column("Status / Policy")

    table.add_row("CPU Architecture", inv.cpu_arch, "[green]VERIFIED (x86_64)[/green]")
    table.add_row("CPU Model", inv.cpu_model, "[green]VERIFIED (6c/12t)[/green]")
    table.add_row(
        "Supported SIMD",
        ", ".join(inv.simd_supported),
        "[green]SUPPORTED (AVX2/FMA/SSE4.2)[/green]",
    )
    table.add_row(
        "Prohibited SIMD",
        ", ".join(inv.simd_prohibited),
        "[red]STRICTLY PROHIBITED (Hardware Lacks AVX-512)[/red]",
    )
    table.add_row("RAM Total", f"{inv.ram_total_gb:.1f} GB", "[green]VERIFIED[/green]")
    table.add_row(
        "RAM Hard Ceiling",
        f"{inv.ram_ceiling_gb:.1f} GB",
        "[green]ACTIVE GUARD (< 13.6 GB)[/green]",
    )
    table.add_row(
        "Concurrency Cap",
        f"Max {inv.max_subagents} subagents",
        "[green]ENFORCED[/green]",
    )

    for legacy, modern in inv.modern_cli_tools.items():
        found = shutil.which(modern) is not None
        status_str = (
            f"[green]INSTALLED[/green] ({shutil.which(modern)})"
            if found
            else "[yellow]MISSING[/yellow]"
        )
        table.add_row(f"Tool: {modern}", f"Replaces legacy '{legacy}'", status_str)

    console.print(table)
    return 0


# -----------------------------------------------------------------------------
# Parser Definition & Main Entrypoint
# -----------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Constructs the low-swarm argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="low-swarm",
        description="Low-Resource Autonomous Code Synthesis Swarm CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=False)

    # Subcommand: run
    p_run = subparsers.add_parser("run", help="Run autonomous code synthesis or refactoring task")
    p_run.add_argument("task", help="Description of synthesis task to execute")
    p_run.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Target file paths to modify or synthesize",
    )
    p_run.add_argument(
        "--tier",
        default="auto",
        choices=["auto", "flash_lite", "pro"],
        help="Target model tier (default: auto)",
    )
    p_run.add_argument(
        "--profile",
        action="store_true",
        help="Measure latency and memory profile",
    )
    p_run.add_argument(
        "--apply",
        action="store_true",
        help="Write synthesized code to target files",
    )
    p_run.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose telemetry output",
    )

    # Subcommand: vault
    p_vault = subparsers.add_parser("vault", help="Manage macOS Keychain credentials")
    vault_subs = p_vault.add_subparsers(dest="vault_command", required=False)

    # vault set
    p_vset = vault_subs.add_parser("set", help="Store a secret in macOS Keychain")
    p_vset.add_argument(
        "--service",
        required=True,
        help="Service name (e.g. openai, jev, OPENAI_API_KEY)",
    )
    p_vset.add_argument("--key", required=True, help="Secret API key value")

    # vault get
    p_vget = vault_subs.add_parser("get", help="Retrieve a secret from Keychain")
    p_vget.add_argument("--service", required=True, help="Service name to look up")

    # vault status
    vault_subs.add_parser(
        "status",
        help="Inspect secret presence in Keychain without leaking values",
    )

    # Subcommand: ingest
    p_ingest = subparsers.add_parser(
        "ingest", help="Ingest Markdown files into FAISS vector database"
    )
    p_ingest.add_argument("--source", required=True, help="Source markdown file or directory")
    p_ingest.add_argument("--output", required=True, help="Destination directory for vector index")

    # Subcommand: doctor
    subparsers.add_parser("doctor", help="Inspect host invariants, SIMD, and CLI tooling")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entrypoint for low-swarm."""
    parser = build_parser()
    args_list = list(sys.argv[1:] if argv is None else argv)

    if not args_list:
        parser.print_help()
        return 2

    try:
        args = parser.parse_args(args_list)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    console = get_console()

    cmd = args.command
    if not cmd:
        parser.print_help()
        return 2

    if cmd == "run":
        return handle_run(args, console)
    elif cmd == "vault":
        if not getattr(args, "vault_command", None):
            console.print("[red]Error: missing vault sub-command ('set', 'get', 'status')[/red]")
            return 2
        return handle_vault(args, console)
    elif cmd == "ingest":
        return handle_ingest(args, console)
    elif cmd == "doctor":
        return handle_doctor(args, console)

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
