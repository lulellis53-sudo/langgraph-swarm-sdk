"""Console entry point: an interactive chat REPL over the YAML-defined swarm."""

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="langswarm", description="Chat with a YAML-defined swarm."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to a swarm YAML file (default: LANGSWARM_CONFIG_PATH).",
    )
    parser.add_argument("--thread-id", default=None)
    args = parser.parse_args()

    from langswarm.config import settings
    from langswarm.log import setup_logging
    from langswarm.observability import tracing_ready

    setup_logging(settings.log_level, json_logs=settings.log_json)

    from langswarm.blueprint import load_blueprint
    from langswarm.runner import run_swarm
    from langswarm.swarm import build_from_blueprint

    config_path = args.config or settings.config_path
    thread_id = args.thread_id or settings.thread_id
    blueprint = load_blueprint(config_path)
    app = build_from_blueprint(blueprint)

    if tracing_ready():
        project = os.environ.get("LANGSMITH_PROJECT", "default")
        print(f"LangSmith tracing enabled (project: {project}).")
    else:
        print(
            "LangSmith tracing disabled. "
            "Set LANGSMITH_TRACING=true and LANGSMITH_API_KEY to enable it."
        )

    names = ", ".join(agent.name for agent in blueprint.agents)
    print(f"Swarm loaded from {config_path}: {names}.\n")
    print("Type a message, or 'exit' to quit.\n")

    while True:
        try:
            message = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not message or message.lower() in {"exit", "quit"}:
            break
        answer = run_swarm(app, message, thread_id=thread_id)
        print(f"\nswarm > {answer}\n")


if __name__ == "__main__":
    main()
