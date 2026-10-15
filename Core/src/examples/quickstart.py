"""Run one conversation using the YAML swarm definition."""

from pathlib import Path

from langswarm.blueprint import load_blueprint
from langswarm.config import settings
from langswarm.runner import run_swarm
from langswarm.swarm import build_from_blueprint


def main() -> None:
    config = Path(__file__).parents[1] / "config" / "swarm.yaml"
    app = build_from_blueprint(load_blueprint(config))
    answer = run_swarm(
        app,
        "Inspect the sample dataset and compute 2**10.",
        thread_id=settings.thread_id,
    )
    print(answer)


if __name__ == "__main__":
    main()
