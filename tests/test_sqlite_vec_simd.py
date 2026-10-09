"""Unit tests for sqlite-vec SIMD feature detection and hardware fallback gating."""

import pytest
from swarm_sdk.memory.sqlite_vec import SqliteVecStore, detect_cpu_simd_features


def test_detect_cpu_simd_features_returns_dict():
    """Verify detect_cpu_simd_features returns expected boolean feature flags."""
    features = detect_cpu_simd_features()
    assert isinstance(features, dict)
    assert "avx2" in features
    assert "fma" in features
    assert "avx512" in features
    assert isinstance(features["avx2"], bool)


def test_sqlite_vec_store_initialization_with_simd_check(tmp_path):
    """Verify SqliteVecStore initializes cleanly with SIMD gating active."""
    db_path = str(tmp_path / "test_simd.sqlite3")
    store = SqliteVecStore(db_path, dim=128)
    assert store.dim == 128
    store.close()
