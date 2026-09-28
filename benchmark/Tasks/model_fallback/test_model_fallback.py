from swarm_sdk.config.loader import load_swarm_config
from swarm_sdk.models.selection import FallbackChain


def test_model_routes_predefined() -> None:
    cfg = load_swarm_config()
    chain = FallbackChain(cfg.model_select, cfg.circuit_breaker)
    assert len(cfg.model_select.routes) >= 1
    assert chain.breakers
