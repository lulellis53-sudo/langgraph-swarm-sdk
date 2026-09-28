from swarm_sdk.model_select import FallbackChain
from swarm_sdk.yaml_config import load_swarm_config


def test_model_routes_predefined() -> None:
    cfg = load_swarm_config()
    chain = FallbackChain(cfg.model_select, cfg.circuit_breaker)
    assert len(cfg.model_select.routes) >= 1
    assert chain.breakers
