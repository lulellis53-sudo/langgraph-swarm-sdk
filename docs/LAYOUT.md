# Repository layout

This page describes the checkout at the repository root. Paths are relative to
that root; use the root `README.md` for installation and runtime commands.

```text
Swarm/
├── Agents/                 # Agent manifests, contracts, orchestration
│   └── benchmark/          # Benchmark tasks and SDK test suite
├── Main/config/            # Runtime, provider, and model configuration
├── Main/                   # Compatibility exports and project resources
├── WebSearch/              # Web search integration and pipeline
├── docs/                   # Guides, research notes, designs, and plans
├── src/swarm_sdk/          # Python SDK and runtime implementation
│   ├── memory/             # Memory backends
│   ├── orchestrator/       # Plan creation and dependency-wave execution
│   ├── pb/                 # Protobuf source and generated gRPC modules
│   ├── retrieval/          # Embeddings, retrieval, reranking, and cache
│   ├── serving/            # FastAPI and gRPC services
│   └── server/             # LangGraph Server graph factories
├── tests/                  # Additional project tests
├── langgraph.json          # LangGraph Server graph registry
├── pyproject.toml          # Package metadata and tooling configuration
└── README.md               # Project setup and supported behavior
```

## Start here

- [Project documentation index](README.md)
- [Root README](../README.md)
- [WebSearch pipeline guide](../WebSearch/PIPELINE.md)
- [Benchmark and test guide](../Agents/benchmark/README.md)
- [Runtime configuration](../Main/config/swarm.yaml)
- [LangGraph Server manifest](../langgraph.json)

`docs/` contains both project guidance and research/design material. Research
notes and archived plans are not evidence that a feature is implemented. Check
the source code, configuration, and tests before relying on an implementation
claim.
