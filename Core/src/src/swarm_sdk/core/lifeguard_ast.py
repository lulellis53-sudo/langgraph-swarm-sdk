"""AST-based safety auditor for swarm modules and plugins.

Performs static analysis to prohibit dangerous top-level execution calls
(e.g., shell executions, destructive filesystem operations, raw sockets)
at module import time, and enforces lazy importing of heavy packages
to protect low-resource hardware.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

HEAVY_MODULES: frozenset[str] = frozenset(
    {
        "torch",
        "transformers",
        "pandas",
        "polars",
        "scipy",
        "sklearn",
    }
)

EXACT_PROHIBITED_CALLS: frozenset[str] = frozenset(
    {
        "os.system",
        "os.popen",
        "eval",
        "builtins.eval",
        "exec",
        "builtins.exec",
        "shutil.rmtree",
        "os.remove",
        "os.unlink",
    }
)

PROHIBITED_PREFIXES: tuple[str, ...] = (
    "subprocess.",
    "socket.",
)

OS_WILDCARD_SYMBOLS: frozenset[str] = frozenset(
    {
        "system",
        "popen",
        "remove",
        "unlink",
    }
)

SUBPROCESS_WILDCARD_SYMBOLS: frozenset[str] = frozenset(
    {
        "run",
        "Popen",
        "call",
        "check_call",
        "check_output",
        "getoutput",
        "getstatusoutput",
    }
)

SHUTIL_WILDCARD_SYMBOLS: frozenset[str] = frozenset(
    {
        "rmtree",
    }
)

SOCKET_WILDCARD_SYMBOLS: frozenset[str] = frozenset(
    {
        "socket",
        "create_connection",
    }
)


class LifeguardViolation(BaseModel):
    """Represents a single static analysis violation."""

    line: int
    col: int
    category: str  # "prohibited_call", "unlazy_import", "syntax_error", "prohibited_operation"
    message: str


class LifeguardAuditReport(BaseModel):
    """Comprehensive audit report returned after scanning module AST."""

    is_approved: bool
    violations: list[LifeguardViolation] = Field(default_factory=list)
    inspected_nodes: int = 0
    has_prohibited_calls: bool = False
    has_unlazy_imports: bool = False


def _get_call_name(node: ast.AST) -> str:
    """Extract a dotted name from a call func node (e.g. os.system or func)."""
    parts: list[str] = []
    curr: ast.AST = node
    while isinstance(curr, ast.Attribute):
        parts.append(curr.attr)
        curr = curr.value
    if isinstance(curr, ast.Name):
        parts.append(curr.id)
        return ".".join(reversed(parts))
    return ""


class _ClassOrInstanceAuditMethod:
    """Descriptor enabling audit_code to be called as a classmethod or instance method."""

    def __init__(self, func: Callable[..., Any]) -> None:
        self.func = func

    def __get__(self, instance: Any, owner: type | None = None) -> Callable[..., Any]:
        if instance is None:
            assert owner is not None

            def class_wrapper(code: str, enforce_lazy: bool = False) -> LifeguardAuditReport:
                auditor = owner(enforce_lazy=enforce_lazy)
                return auditor.audit(code, enforce_lazy=enforce_lazy)

            return class_wrapper

        def instance_wrapper(
            code: str,
            enforce_lazy: bool | None = None,
        ) -> LifeguardAuditReport:
            lazy = instance.enforce_lazy if enforce_lazy is None else enforce_lazy
            return instance.audit(code, enforce_lazy=lazy)

        return instance_wrapper


class MetaLifeguardAuditor(ast.NodeVisitor):
    """AST visitor that checks for dangerous module-level calls and unlazy imports."""

    def __init__(self, enforce_lazy: bool = False) -> None:
        """Initialize the AST auditor with the repo's lazy-import rules."""
        super().__init__()
        self.enforce_lazy = enforce_lazy
        self.source_code: str = ""
        self.lines: list[str] = []
        self.violations: list[LifeguardViolation] = []
        self.inspected_nodes: int = 0
        self.scope_stack: list[str] = ["module"]
        self.aliases: dict[str, str] = {}

    @property
    def is_module_scope(self) -> bool:
        """True if currently visiting at the top-level module scope."""
        return len(self.scope_stack) == 1 and self.scope_stack[0] == "module"

    def _resolve_call_name(self, raw_name: str) -> str:
        """Resolve aliases established via imports."""
        if not raw_name:
            return ""
        if raw_name in self.aliases:
            return self.aliases[raw_name]
        if "." in raw_name:
            prefix, rest = raw_name.split(".", 1)
            if prefix in self.aliases:
                aliased_prefix = self.aliases[prefix]
                return f"{aliased_prefix}.{rest}"
        return raw_name

    def _is_main_guard(self, node: ast.If) -> bool:
        """Check if an ast.If represents `if __name__ == '__main__':`."""
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
        ):
            left = test.left
            right = test.comparators[0]
            if (
                isinstance(left, ast.Name)
                and left.id == "__name__"
                and isinstance(right, ast.Constant)
                and right.value == "__main__"
            ):
                return True
            if (
                isinstance(right, ast.Name)
                and right.id == "__name__"
                and isinstance(left, ast.Constant)
                and left.value == "__main__"
            ):
                return True
        return False

    def _is_type_checking_guard(self, node: ast.If) -> bool:
        """Check if an ast.If represents `if TYPE_CHECKING:`."""
        test = node.test
        if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
            return True
        if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
            return True
        return False

    def _is_marked_lazy(self, lineno: int) -> bool:
        """Check if an import is marked with an inline or preceding comment."""
        marker_keywords = ("noqa", "lazy", "lifeguard", "ignore", "allow")
        # Check current line
        if 0 <= lineno - 1 < len(self.lines):
            line = self.lines[lineno - 1]
            if "#" in line:
                comment = line.split("#", 1)[1].strip().lower()
                if any(k in comment for k in marker_keywords):
                    return True
        # Check preceding line
        if 0 <= lineno - 2 < len(self.lines):
            prev_line = self.lines[lineno - 2].strip()
            if prev_line.startswith("#"):
                comment = prev_line.lstrip("#").strip().lower()
                if any(k in comment for k in marker_keywords):
                    return True
        return False

    def _is_write_open(self, node: ast.Call, resolved_name: str) -> tuple[bool, str]:
        """Check if open() or Path.open() is invoked with write/append mode."""
        is_builtin_open = resolved_name in ("open", "builtins.open", "io.open")
        is_path_open = isinstance(node.func, ast.Attribute) and node.func.attr == "open"

        if not (is_builtin_open or is_path_open):
            return False, ""

        mode_val: str | None = None

        # Check positional mode argument
        # For builtin open(file, mode='r', ...): mode is args[1]
        # For Path.open(mode='r', ...): mode is args[0]
        mode_idx = 1 if is_builtin_open else 0
        if len(node.args) > mode_idx:
            arg_node = node.args[mode_idx]
            if isinstance(arg_node, ast.Constant) and isinstance(arg_node.value, str):
                mode_val = arg_node.value

        # Check keyword argument mode=...
        for kw in node.keywords:
            if (
                kw.arg == "mode"
                and isinstance(kw.value, ast.Constant)
                and isinstance(kw.value.value, str)
            ):
                mode_val = kw.value.value

        if mode_val is not None:
            normalized = mode_val.lower()
            if any(char in normalized for char in ("w", "a", "x", "+")):
                return True, f"Prohibited write/append mode '{mode_val}' in open() call"

        return False, ""

    def _is_prohibited_call(self, node: ast.Call) -> tuple[bool, str]:
        """Determine if a top-level call is prohibited."""
        raw_name = _get_call_name(node.func)
        resolved_name = self._resolve_call_name(raw_name)

        # Check open() / Path.open() write/append
        is_write, open_msg = self._is_write_open(node, resolved_name)
        if is_write:
            return True, open_msg

        # Check exact matches (os.system, os.popen, eval, exec, shutil.rmtree, os.remove, os.unlink)
        if resolved_name in EXACT_PROHIBITED_CALLS:
            return True, f"Prohibited top-level execution call: '{resolved_name}'"

        # Check subprocess.*
        if resolved_name.startswith("subprocess."):
            return True, f"Prohibited top-level execution call: '{resolved_name}'"

        # Check socket.* or direct socket constructor
        if resolved_name.startswith("socket.") or resolved_name == "socket":
            return True, f"Prohibited top-level execution call: '{resolved_name}'"

        return False, ""

    def visit(self, node: ast.AST) -> Any:
        """Count inspected nodes and dispatch."""
        self.inspected_nodes += 1
        return super().visit(node)

    def visit_Import(self, node: ast.Import) -> Any:
        """Track module imports and flag heavy imports if enforce_lazy."""
        for alias in node.names:
            name = alias.name
            asname = alias.asname or name
            self.aliases[asname] = name

            root = name.split(".")[0]
            if self.enforce_lazy and self.is_module_scope and root in HEAVY_MODULES:
                if not self._is_marked_lazy(node.lineno):
                    self.violations.append(
                        LifeguardViolation(
                            line=node.lineno,
                            col=node.col_offset,
                            category="unlazy_import",
                            message=(
                                f"Heavy module '{name}' imported at module scope; "
                                "use lazy import or place inside a function or TYPE_CHECKING guard"
                            ),
                        )
                    )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        """Track from imports and flag heavy imports if enforce_lazy."""
        mod = node.module or ""
        for alias in node.names:
            name = alias.name
            asname = alias.asname or name

            if name == "*":
                # Handle wildcard imports for security tracking
                if mod == "os":
                    for sym in OS_WILDCARD_SYMBOLS:
                        self.aliases[sym] = f"os.{sym}"
                elif mod == "subprocess":
                    for sym in SUBPROCESS_WILDCARD_SYMBOLS:
                        self.aliases[sym] = f"subprocess.{sym}"
                elif mod == "shutil":
                    for sym in SHUTIL_WILDCARD_SYMBOLS:
                        self.aliases[sym] = f"shutil.{sym}"
                elif mod == "socket":
                    for sym in SOCKET_WILDCARD_SYMBOLS:
                        self.aliases[sym] = f"socket.{sym}"
            else:
                full_name = f"{mod}.{name}" if mod else name
                self.aliases[asname] = full_name

        root = mod.split(".")[0] if mod else ""
        if self.enforce_lazy and self.is_module_scope and root in HEAVY_MODULES:
            if not self._is_marked_lazy(node.lineno):
                self.violations.append(
                    LifeguardViolation(
                        line=node.lineno,
                        col=node.col_offset,
                        category="unlazy_import",
                        message=(
                            f"Heavy module '{mod}' imported at module scope; "
                            "use lazy import or place inside a function or TYPE_CHECKING guard"
                        ),
                    )
                )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        """Visit decorators/defaults in outer scope, body in function scope."""
        for d in node.decorator_list:
            self.visit(d)
        for a in node.args.defaults:
            self.visit(a)
        for a in node.args.kw_defaults:
            if a is not None:
                self.visit(a)
        if node.returns is not None:
            self.visit(node.returns)

        self.scope_stack.append("function")
        for stmt in node.body:
            self.visit(stmt)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        """Visit async function body in function scope."""
        for d in node.decorator_list:
            self.visit(d)
        for a in node.args.defaults:
            self.visit(a)
        for a in node.args.kw_defaults:
            if a is not None:
                self.visit(a)
        if node.returns is not None:
            self.visit(node.returns)

        self.scope_stack.append("function")
        for stmt in node.body:
            self.visit(stmt)
        self.scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        """Visit class body in class scope."""
        for d in node.decorator_list:
            self.visit(d)
        for b in node.bases:
            self.visit(b)
        for k in node.keywords:
            self.visit(k)

        self.scope_stack.append("class")
        for stmt in node.body:
            self.visit(stmt)
        self.scope_stack.pop()

    def visit_Lambda(self, node: ast.Lambda) -> Any:
        """Visit lambda body in lambda scope."""
        for a in node.args.defaults:
            self.visit(a)
        for a in node.args.kw_defaults:
            if a is not None:
                self.visit(a)

        self.scope_stack.append("lambda")
        self.visit(node.body)
        self.scope_stack.pop()

    def visit_If(self, node: ast.If) -> Any:
        """Handle conditional execution, recognizing main and type checking guards."""
        self.visit(node.test)
        if self._is_main_guard(node):
            self.scope_stack.append("main_guard")
            for stmt in node.body:
                self.visit(stmt)
            self.scope_stack.pop()
        elif self._is_type_checking_guard(node):
            self.scope_stack.append("type_checking")
            for stmt in node.body:
                self.visit(stmt)
            self.scope_stack.pop()
        else:
            for stmt in node.body:
                self.visit(stmt)

        for stmt in node.orelse:
            self.visit(stmt)

    def visit_Call(self, node: ast.Call) -> Any:
        """Intercept calls at module scope and check for prohibited operations."""
        if self.is_module_scope:
            is_prohibited, msg = self._is_prohibited_call(node)
            if is_prohibited:
                self.violations.append(
                    LifeguardViolation(
                        line=node.lineno,
                        col=node.col_offset,
                        category="prohibited_call",
                        message=msg,
                    )
                )
        self.generic_visit(node)

    def audit(self, code: str, enforce_lazy: bool | None = None) -> LifeguardAuditReport:
        """Audit Python source code and return a LifeguardAuditReport."""
        if enforce_lazy is not None:
            self.enforce_lazy = enforce_lazy

        self.source_code = code
        self.lines = code.splitlines()
        self.violations = []
        self.inspected_nodes = 0
        self.scope_stack = ["module"]
        self.aliases = {}

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return LifeguardAuditReport(
                is_approved=False,
                violations=[
                    LifeguardViolation(
                        line=e.lineno or 1,
                        col=e.offset or 0,
                        category="syntax_error",
                        message=f"Syntax error: {e.msg if hasattr(e, 'msg') else str(e)}",
                    )
                ],
                inspected_nodes=0,
                has_prohibited_calls=False,
                has_unlazy_imports=False,
            )

        self.visit(tree)

        has_prohibited = any(v.category == "prohibited_call" for v in self.violations)
        has_unlazy = any(v.category == "unlazy_import" for v in self.violations)
        is_approved = len(self.violations) == 0

        return LifeguardAuditReport(
            is_approved=is_approved,
            violations=self.violations,
            inspected_nodes=self.inspected_nodes,
            has_prohibited_calls=has_prohibited,
            has_unlazy_imports=has_unlazy,
        )

    audit_code = _ClassOrInstanceAuditMethod(audit)


def audit_code(code: str, enforce_lazy: bool = False) -> LifeguardAuditReport:
    """Convenience function to audit Python code against lifeguard invariants."""
    return MetaLifeguardAuditor.audit_code(code, enforce_lazy=enforce_lazy)
