from __future__ import annotations

import pytest

from swarm_sdk.core.lifeguard_ast import (
    LifeguardAuditReport,
    LifeguardViolation,
    MetaLifeguardAuditor,
    audit_code,
)


def test_safe_code():
    code = """
import math
import sys
from pathlib import Path

CONSTANT = 42

def add(a: int, b: int) -> int:
    return a + b

class Calculator:
    def multiply(self, a: int, b: int) -> int:
        return a * b
"""
    report = MetaLifeguardAuditor.audit_code(code)
    assert isinstance(report, LifeguardAuditReport)
    assert report.is_approved is True
    assert len(report.violations) == 0
    assert report.inspected_nodes > 0
    assert report.has_prohibited_calls is False
    assert report.has_unlazy_imports is False


def test_syntax_error_handling():
    bad_code = "def broken_syntax(:\n    pass"
    report = MetaLifeguardAuditor.audit_code(bad_code)
    assert report.is_approved is False
    assert len(report.violations) == 1
    v = report.violations[0]
    assert isinstance(v, LifeguardViolation)
    assert v.category == "syntax_error"
    assert v.line == 1
    assert "Syntax" in v.message or "syntax" in v.message.lower()
    assert report.inspected_nodes == 0
    assert report.has_prohibited_calls is False
    assert report.has_unlazy_imports is False


@pytest.mark.parametrize(
    "code_snippet,expected_name",
    [
        ('os.system("echo dangerous")', "os.system"),
        ('os.popen("cat /etc/passwd")', "os.popen"),
        ('subprocess.run(["ls", "-l"])', "subprocess.run"),
        ('subprocess.Popen(["sleep", "10"])', "subprocess.Popen"),
        ('subprocess.call(["date"])', "subprocess.call"),
        ('subprocess.check_call(["whoami"])', "subprocess.check_call"),
        ('subprocess.check_output(["uname", "-a"])', "subprocess.check_output"),
        ('eval("2 + 2")', "eval"),
        ('exec("x = 10")', "exec"),
        ("socket.socket()", "socket.socket"),
        ('socket.create_connection(("127.0.0.1", 80))', "socket.create_connection"),
        ('shutil.rmtree("/tmp/target")', "shutil.rmtree"),
        ('os.remove("/tmp/file.txt")', "os.remove"),
        ('os.unlink("/tmp/file.txt")', "os.unlink"),
    ],
)
def test_prohibited_top_level_calls(code_snippet: str, expected_name: str):
    code = f"""
import os, subprocess, socket, shutil
{code_snippet}
"""
    report = MetaLifeguardAuditor.audit_code(code)
    assert report.is_approved is False
    assert report.has_prohibited_calls is True
    assert any(
        v.category == "prohibited_call" and expected_name in v.message for v in report.violations
    )


@pytest.mark.parametrize(
    "call_expr",
    [
        'open("out.txt", "w")',
        'open("out.txt", "wb")',
        'open("out.txt", "a")',
        'open("out.txt", "w+")',
        'open("out.txt", "a+")',
        'open("out.txt", mode="w")',
        'open("out.txt", mode="wb")',
        'open("out.txt", mode="a")',
        'open("out.txt", mode="w+")',
        'open("out.txt", mode="a+")',
    ],
)
def test_prohibited_top_level_open_writes(call_expr: str):
    code = f"""
f = {call_expr}
"""
    report = MetaLifeguardAuditor.audit_code(code)
    assert report.is_approved is False
    assert report.has_prohibited_calls is True
    assert any(v.category == "prohibited_call" and "open" in v.message for v in report.violations)


def test_prohibited_with_open_write():
    code = """
with open("log.txt", "w") as f:
    f.write("entry")
"""
    report = MetaLifeguardAuditor.audit_code(code)
    assert report.is_approved is False
    assert report.has_prohibited_calls is True
    assert any(v.category == "prohibited_call" and "open" in v.message for v in report.violations)


@pytest.mark.parametrize(
    "safe_open_expr",
    [
        'open("read.txt")',
        'open("read.txt", "r")',
        'open("read.txt", "rb")',
        'open("read.txt", mode="r")',
        'open("read.txt", mode="rb")',
    ],
)
def test_allowed_top_level_open_reads(safe_open_expr: str):
    code = f"""
f = {safe_open_expr}
with {safe_open_expr} as fp:
    data = fp.read()
"""
    report = MetaLifeguardAuditor.audit_code(code)
    assert report.is_approved is True
    assert report.has_prohibited_calls is False
    assert len(report.violations) == 0


def test_prohibited_calls_enclosed_in_functions_are_allowed():
    code = """
import os, subprocess, shutil, socket

def worker():
    os.system("echo ok")
    subprocess.run(["ls"])
    eval("1 + 1")
    exec("x = 1")
    socket.socket()
    with open("temp.txt", "w") as f:
        f.write("hello")
    shutil.rmtree("/tmp/test")
    os.remove("/tmp/foo")
    os.unlink("/tmp/bar")

async def async_worker():
    os.system("echo async")
    subprocess.Popen(["sleep", "1"])
"""
    report = MetaLifeguardAuditor.audit_code(code)
    assert report.is_approved is True
    assert report.has_prohibited_calls is False
    assert len(report.violations) == 0


def test_prohibited_calls_enclosed_in_class_are_allowed():
    code = """
import os, subprocess

class SafeService:
    def start(self):
        os.system("service start")
        subprocess.check_call(["echo", "ready"])
"""
    report = MetaLifeguardAuditor.audit_code(code)
    assert report.is_approved is True
    assert report.has_prohibited_calls is False
    assert len(report.violations) == 0


def test_prohibited_calls_enclosed_in_main_guard_are_allowed():
    code = """
import os, subprocess, shutil

if __name__ == '__main__':
    os.system("echo running main")
    subprocess.run(["pytest"])
    shutil.rmtree("/tmp/cache")
"""
    report = MetaLifeguardAuditor.audit_code(code)
    assert report.is_approved is True
    assert report.has_prohibited_calls is False
    assert len(report.violations) == 0


def test_prohibited_calls_enclosed_in_reversed_main_guard_are_allowed():
    code = """
import os

if '__main__' == __name__:
    os.system("echo reversed main")
"""
    report = MetaLifeguardAuditor.audit_code(code)
    assert report.is_approved is True
    assert report.has_prohibited_calls is False
    assert len(report.violations) == 0


def test_prohibited_calls_in_loops_and_non_main_conditionals_are_flagged():
    code = """
import os

if True:
    os.system("echo in condition")

for _ in range(1):
    os.system("echo in loop")

try:
    os.system("echo in try")
except Exception:
    pass
"""
    report = MetaLifeguardAuditor.audit_code(code)
    assert report.is_approved is False
    assert report.has_prohibited_calls is True
    assert len(report.violations) == 3


def test_prohibited_calls_in_function_defaults_are_flagged():
    code = """
import os

def dangerous_default(val=os.system("id")):
    return val
"""
    report = MetaLifeguardAuditor.audit_code(code)
    assert report.is_approved is False
    assert report.has_prohibited_calls is True
    assert any("os.system" in v.message for v in report.violations)


def test_imported_aliases_detected():
    code = """
from os import system as sys_call
from subprocess import run, Popen as Process
from shutil import rmtree
from socket import socket

sys_call("whoami")
run(["ls"])
p = Process(["sleep", "1"])
rmtree("/tmp/folder")
s = socket()
"""
    report = MetaLifeguardAuditor.audit_code(code)
    assert report.is_approved is False
    assert report.has_prohibited_calls is True
    assert len(report.violations) == 5


@pytest.mark.parametrize(
    "heavy_import",
    [
        "import torch",
        "import torch.nn as nn",
        "from torch import tensor",
        "import transformers",
        "from transformers import AutoTokenizer",
        "import pandas as pd",
        "from pandas import DataFrame",
        "import polars as pl",
        "from polars import col",
        "import scipy",
        "from scipy import stats",
        "import sklearn",
        "from sklearn.linear_model import LogisticRegression",
    ],
)
def test_heavy_modules_lazy_enforcement(heavy_import: str):
    # Without enforce_lazy: approved
    report_lenient = MetaLifeguardAuditor.audit_code(heavy_import, enforce_lazy=False)
    assert report_lenient.is_approved is True
    assert report_lenient.has_unlazy_imports is False
    assert len(report_lenient.violations) == 0

    # With enforce_lazy: flagged
    report_strict = MetaLifeguardAuditor.audit_code(heavy_import, enforce_lazy=True)
    assert report_strict.is_approved is False
    assert report_strict.has_unlazy_imports is True
    assert any(v.category == "unlazy_import" for v in report_strict.violations)


def test_heavy_modules_lazy_patterns_allowed():
    code = """
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import torch
    from transformers import AutoTokenizer
    import pandas as pd

def get_torch():
    import torch
    import polars as pl
    return torch

class HeavyModelWrapper:
    def load(self):
        import scipy
        from sklearn.cluster import KMeans
        return KMeans()

if __name__ == '__main__':
    import torch
"""
    report = MetaLifeguardAuditor.audit_code(code, enforce_lazy=True)
    assert report.is_approved is True
    assert report.has_unlazy_imports is False
    assert len(report.violations) == 0


def test_heavy_modules_comment_markers_allowed():
    code = """
import torch  # noqa
import pandas as pd  # lifeguard: allow
from transformers import pipeline  # lazy: ok
# lifeguard: allow
import polars as pl
"""
    report = MetaLifeguardAuditor.audit_code(code, enforce_lazy=True)
    assert report.is_approved is True
    assert report.has_unlazy_imports is False
    assert len(report.violations) == 0


def test_multiple_violations_combined():
    code = """
import os
import torch

os.system("ls")
subprocess.run(["pwd"])
"""
    report = MetaLifeguardAuditor.audit_code(code, enforce_lazy=True)
    assert report.is_approved is False
    assert report.has_prohibited_calls is True
    assert report.has_unlazy_imports is True
    assert len(report.violations) == 3


def test_auditor_callable_patterns():
    # Classmethod call
    rep1 = MetaLifeguardAuditor.audit_code("x = 1")
    assert rep1.is_approved is True

    # Standalone function
    rep2 = audit_code("x = 1")
    assert rep2.is_approved is True

    # Instance call
    auditor = MetaLifeguardAuditor(enforce_lazy=True)
    rep3 = auditor.audit_code("import torch")
    assert rep3.is_approved is False
    assert rep3.has_unlazy_imports is True


def test_core_reexports():
    import swarm_sdk.core as core

    assert hasattr(core, "LifeguardAuditReport")
    assert hasattr(core, "LifeguardViolation")
    assert hasattr(core, "MetaLifeguardAuditor")
    assert hasattr(core, "audit_code")
    assert core.LifeguardAuditReport is LifeguardAuditReport
    assert core.LifeguardViolation is LifeguardViolation
    assert core.MetaLifeguardAuditor is MetaLifeguardAuditor
