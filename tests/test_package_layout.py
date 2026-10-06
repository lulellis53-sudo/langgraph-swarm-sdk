"""Pins the merged package layout: new modules import, old packages are gone."""

from __future__ import annotations

import importlib

import pytest

REMOVED: list[str] = []
PRESENT: list[str] = []


@pytest.mark.parametrize("name", REMOVED)
def test_old_package_is_gone(name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(name)


@pytest.mark.parametrize("name", PRESENT)
def test_new_module_imports(name: str) -> None:
    importlib.import_module(name)
