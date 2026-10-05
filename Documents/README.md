# Documentation index

Use the root [README](../README.md) for supported setup, configuration, and
runtime behavior. This folder also contains research notes and historical design
records; those are not product guarantees. Verify implementation details in the
linked source, configuration, and tests before applying them.

## Project guides

- [Repository layout](LAYOUT.md) — where the project's main components live.
- [WebSearch workflow](workflow.md) — search, fetch, and extraction flow.
- [Google dork queries](dorks.md) — query builder syntax and examples.
- [LangGraph Swarm reference](LangGraphSwarm.md) — project architecture and
  selected LangGraph concepts. Code examples are illustrative unless marked as
  project-verified.
- [Perplexity integration notes](perplexity_playwright_guide.md) — use the documented API for integrations.

## Research and design notes

- [RAG techniques](RAGTECHNIQUES.MD)
- [Low-resource optimization](LowResourceOptimization.md)
- [Memory allocators](MemoryAllocators.md)
- [Python 3.15](Python3.15.md)
- [MoltenVK and Vulkan](Molten.md)
- [Agent methods](AgenticMethod.MD)
- [Liveboard design](design-liveboard.md)
- [`superpowers/specs/`](superpowers/specs/) and [`superpowers/plans/`](superpowers/plans/)
  contain dated design records and implementation plans.

Research documents may discuss external systems, preview features, or hardware
that this project does not use. Treat performance figures as unverified unless
the document links a reproducible benchmark, its workload, and its results.
