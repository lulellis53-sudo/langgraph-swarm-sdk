"""WebSearch agentic benchmark: does a model use the search tool and answer from the hits?

Offline (CI): a scripted model drives a real ``create_agent`` loop over the real
``websearch_langchain_tools`` with canned provider backends. Measured per run:
tool calls and their arguments, URLs the answer cites, groundedness (every cited URL
came back from the tool), and tokens (model usage plus ``count_text`` of the tool
output that entered the prompt).

Live (``--live MODEL``): the same loop with ``load_chat_model(MODEL)`` and the real
providers; prints the per-provider report from ``search_report`` first. Uses API keys
and spends tokens, so it is never run by CI::

    uv run python -m benchmark.Tasks.websearch_agentic.benchmark_websearch_agentic \
        --live zai:glm-5.3 --prompt "lightgbm forecasting" --after 2026-06-01
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from WebSearch.frontend.report import search_report
from WebSearch.frontend.websearchers import ProvidersConfig, SearchFn, load_providers
from WebSearch.langchain_tools import websearch_langchain_tools

from swarm_sdk.prompting.budget import count_text

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

_URL = re.compile(r"https?://[^\s)\]>\"']+")


@dataclass(frozen=True, slots=True)
class AgentRun:
    """What the agent did for one prompt.

    Attributes:
        answer: Final assistant text.
        tool_calls: ``(tool name, args)`` in call order.
        tool_urls: URLs present in tool outputs.
        cited_urls: URLs in the final answer.
        ungrounded: Cited URLs that no tool output contained (hallucinations).
        model_tokens: Sum of ``usage_metadata.total_tokens`` over model replies.
        tool_tokens: ``count_text`` of tool output that entered the prompt.
    """

    answer: str
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    tool_urls: list[str] = field(default_factory=list)
    cited_urls: list[str] = field(default_factory=list)
    ungrounded: list[str] = field(default_factory=list)
    model_tokens: int = 0
    tool_tokens: int = 0

    @property
    def grounded(self) -> bool:
        """True when the answer cites at least one URL and every one is grounded."""
        return bool(self.cited_urls) and not self.ungrounded


def _urls(text: str) -> list[str]:
    return list(dict.fromkeys(u.rstrip(".,;") for u in _URL.findall(text)))


def run_agent(
    prompt: str,
    model: BaseChatModel,
    *,
    backends: Mapping[str, SearchFn] | None = None,
    config: ProvidersConfig | None = None,
) -> AgentRun:
    """Run a tool-calling agent over the WebSearch tools and score the transcript."""
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage, ToolMessage

    tools = websearch_langchain_tools(config=config, backends=backends)
    agent = create_agent(model, tools=tools)
    state = agent.invoke({"messages": [("user", prompt)]})
    messages = state["messages"]

    calls: list[tuple[str, dict[str, Any]]] = []
    tool_text: list[str] = []
    model_tokens = 0
    for message in messages:
        if isinstance(message, AIMessage):
            calls += [(c["name"], dict(c["args"])) for c in message.tool_calls]
            model_tokens += (message.usage_metadata or {}).get("total_tokens", 0)
        elif isinstance(message, ToolMessage):
            tool_text.append(
                message.content if isinstance(message.content, str) else str(message.content)
            )
    final = next(
        (m for m in reversed(messages) if isinstance(m, AIMessage) and not m.tool_calls), None
    )
    answer = "" if final is None else str(final.content)

    tool_urls = _urls("\n".join(tool_text))
    cited = _urls(answer)
    return AgentRun(
        answer=answer,
        tool_calls=calls,
        tool_urls=tool_urls,
        cited_urls=cited,
        ungrounded=[u for u in cited if u not in set(tool_urls)],
        model_tokens=model_tokens,
        tool_tokens=sum(count_text(t) for t in tool_text),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", metavar="MODEL", required=True, help="provider:name chat model")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--after")
    parser.add_argument("--before")
    args = parser.parse_args(argv)

    from WebSearch.frontend.dorks import dork

    from swarm_sdk.models.chat import load_chat_model

    words = [w for w in re.sub(r'["()|]', " ", args.prompt).split()]
    query = (
        dork(*words, after=args.after, before=args.before)
        if (args.after or args.before)
        else args.prompt
    )
    cfg = load_providers()
    report = search_report(query, config=cfg)
    run = run_agent(query, load_chat_model(args.live), config=cfg)
    print(json.dumps({"search": report.to_dict(), "agent": asdict(run)}, indent=2, default=str))
    return 0 if run.grounded else 1


if __name__ == "__main__":
    raise SystemExit(main())
