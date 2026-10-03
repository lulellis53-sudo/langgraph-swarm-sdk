from __future__ import annotations

from pathlib import Path

from benchmark import run as benchmark_run


def test_runner_uses_pytest_when_task_module_has_no_run(tmp_path: Path, monkeypatch) -> None:
    task_dir = tmp_path / "benchmark" / "Tasks" / "sample"
    task_dir.mkdir(parents=True)
    (task_dir / "test_sample.py").write_text("def test_sample(): pass\n", encoding="utf-8")
    monkeypatch.setattr(benchmark_run, "__file__", str(tmp_path / "benchmark" / "run.py"))
    calls: list[list[str]] = []
    monkeypatch.setattr("pytest.main", lambda args: calls.append(list(args)) or 0)

    result = benchmark_run.main(["--task", "sample"])

    assert result == 0
    assert calls == [["-q", str(task_dir)]]
