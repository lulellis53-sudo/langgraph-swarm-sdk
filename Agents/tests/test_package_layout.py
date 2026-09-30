"""Test package structure and import contracts for swarm_sdk domain packages."""

from __future__ import annotations

import importlib

import pytest


def test_import_prompting_and_observability() -> None:
    from swarm_sdk.observability.usage import UsageLog
    from swarm_sdk.prompting.budget import TokenBudget, count_text

    assert TokenBudget is not None
    assert count_text is not None
    assert UsageLog is not None


def test_import_retrieval_domain() -> None:
    from swarm_sdk.retrieval.cache import SemanticCache
    from swarm_sdk.retrieval.embeddings import FastEmbedder, HashEmbedder
    from swarm_sdk.retrieval.hybrid import hybrid_search
    from swarm_sdk.retrieval.recall import recall_texts
    from swarm_sdk.retrieval.rerank import FastEmbedReranker
    from swarm_sdk.retrieval.text import tokenize

    assert FastEmbedder is not None
    assert HashEmbedder is not None
    assert hybrid_search is not None
    assert recall_texts is not None
    assert FastEmbedReranker is not None
    assert SemanticCache is not None
    assert tokenize("hello world") == ["hello", "world"]


def test_import_config_domain() -> None:
    from swarm_sdk.config.loader import default_config_path, load_swarm_config
    from swarm_sdk.config.settings import Settings

    assert Settings is not None
    assert load_swarm_config is not None
    assert default_config_path().exists()


def test_import_models_domain() -> None:
    from swarm_sdk.models.breaker import CircuitBreaker
    from swarm_sdk.models.chat import load_chat_model
    from swarm_sdk.models.registry import Registry
    from swarm_sdk.models.selection import ModelSelector

    assert CircuitBreaker is not None
    assert load_chat_model is not None
    assert Registry is not None
    assert ModelSelector is not None


def test_import_execution_and_gpu() -> None:
    from swarm_sdk.execution.executor import install_uvloop, offload
    from swarm_sdk.execution.fanout import fan_out
    from swarm_sdk.gpu.report import acceleration_report

    assert install_uvloop is not None
    assert offload is not None
    assert fan_out is not None
    assert acceleration_report is not None


def test_import_numpy_polars_sklearn() -> None:
    import numpy as np
    import polars as pl
    import sklearn

    assert np.__version__
    assert pl.__version__
    assert isinstance(sklearn.__version__, str)


def test_import_core_domain() -> None:
    from swarm_sdk.core.swarm import SwarmSDK

    assert SwarmSDK is not None


def test_import_serving_domain() -> None:
    from swarm_sdk.serving.grpc import SwarmServicer
    from swarm_sdk.serving.http import create_app
    from swarm_sdk.serving.peer import post_json

    assert SwarmServicer is not None
    assert create_app is not None
    assert post_json is not None


def test_root_exports() -> None:
    import swarm_sdk
    from swarm_sdk import RunResult, Settings, SwarmSDK

    assert SwarmSDK is not None
    assert Settings is not None
    assert RunResult is not None
    assert hasattr(swarm_sdk, "SwarmSDK")
    assert hasattr(swarm_sdk, "Settings")
    assert hasattr(swarm_sdk, "RunResult")


def test_former_flat_modules_fail_to_import() -> None:
    former_flat = [
        "swarm_sdk.swarm",
        "swarm_sdk.api",
        "swarm_sdk.grpc_server",
        "swarm_sdk.tokens",
        "swarm_sdk.usage",
        "swarm_sdk.embeddings",
        "swarm_sdk.hybrid",
        "swarm_sdk.rerank",
        "swarm_sdk.cache",
        "swarm_sdk.yaml_config",
        "swarm_sdk.providers",
        "swarm_sdk.model_select",
        "swarm_sdk.registry",
        "swarm_sdk.resilience",
        "swarm_sdk.runtime",
        "swarm_sdk.parallel",
        "swarm_sdk.transport",
        "swarm_sdk.accel",
    ]
    for mod in former_flat:
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(mod)


