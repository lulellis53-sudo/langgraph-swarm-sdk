# Documentation index

Use the root [README](../README.md) for supported setup, configuration, and
runtime behavior. This folder also contains research notes and historical design
records; those are not product guarantees. Verify implementation details in the
linked source, configuration, and tests before applying them.

## Project guides

- [Repository layout](LAYOUT.md) — where the project's main components live.
- [WebSearch workflow](workflow.md) — search, fetch, and extraction flow.
- [Google dork queries](dorks.md) — query builder syntax and examples.
- [LangGraph Swarm reference](LangSwarm.md) — canonical architecture manual (merged `LangGraphSwarm.md`, acceleration research)
- [LangGraphSwarm stub](LangGraphSwarm.md) — redirect to `LangSwarm.md`
- [Perplexity integration notes](perplexity_playwright_guide.md) — use the documented API for integrations.

## Research and design notes

- [Redis & caching](REDIS.md) — canonical manual (merged caching + optional SDK Redis cache)
- [Caching architecture](CACHING.md) — redirect stub
- [Optional Redis cache (SDK)](redis-cache.md) — redirect stub
- [RAG techniques](RAGTECHNIQUES.MD) — canonical dossier (merged `RAG.md`)
- [RAG overview stub](RAG.md) — redirect to `RAGTECHNIQUES.MD`
- [Low-resource optimization](LowResourceOptimization.md)
- [Memory allocators](MemoryAllocators.md)
- [Python 3.15](Python3.15.md) — canonical 3.15 / free-threading / performance dossier
- [Python free-threaded runtime](PythonFreeThreadedRuntime.md) — redirect stub
- [Python performance guide](PythonPerformanceGuide.md) — redirect stub
- [Lifeguard](Lifeguard.md) — AST safety, lazy imports, ops self-healing, runtime RSS/`healthz`
- [Enterprise databases](Database.md) — canonical dossier (merged `DATABASE.md`, `DB.md`; `DB.md` stub remains)
- [Agent memory & vector storage](AGENTMEMORY.md) — canonical dossier (merged `VectorDB.md`)
- [Vector DB stub](VectorDB.md) — redirect to `AGENTMEMORY.md`
- [MoltenVK and Vulkan](Molten.md)
- [Agent methods](AgenticMethod.MD)
- [Liveboard design](design-liveboard.md)
- [`superpowers/specs/`](superpowers/specs/) and [`superpowers/plans/`](superpowers/plans/)
  contain dated design records and implementation plans.

Research documents may discuss external systems, preview features, or hardware
that this project does not use. Treat performance figures as unverified unless
the document links a reproducible benchmark, its workload, and its results.
