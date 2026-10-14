# CLI — Personal Agent CLI (base: gemini-cli)

Estrutura de trabalho do meu próprio CLI, derivado do `gemini-cli` como base.
Governado pelo roadmap em [`gemini-cli/DeepResearch.md`](gemini-cli/DeepResearch.md) → **Part XV: Strategic Engineering Roadmap & Production Implementation Directives**.

## Estrutura

```
CLI/
├── gemini-cli/            # Fork base (Google) + DeepResearch.md (documento-mestre, 15 Parts)
├── gemini-cli-tips/       # Repo de dicas/snapshot do upstream
├── mcp-xeon-server/       # Diretriz B — MCP worker remoto (Node/TS) ✅ build ok
├── providers.yaml         # Config de providers LLM
└── scratch/               # Experimentos soltos (adapter-src/)
```

## Status das Diretrizes (Part XV)

| Dir | Objetivo | Alvo | Status |
|-----|----------|------|--------|
| **A** | Ligar roteador Jev System-1 ao dispatch do Swarm | `src/swarm_sdk/core/jev_router.py` (597 ln) + `routing.py` | ✅ **existe** — já importado por 7 módulos (`swarm.py`, `graph.py`, `jev_gate.py`...) |
| **B** | Servidor MCP Xeon remoto (scrape/pgvector/SQL/telemetry) | `CLI/mcp-xeon-server/` | ✅ **criado + build validado** (`dist/index.js`) |
| **C** | Patches de build TS (strip DOM, IC monomórfico) | `gemini-cli/packages/core/tsconfig.json` & `context/graph/types.ts` | 🟡 **parcial** — tsconfig ✅; factory `createMonomorphicNode` criada mas **ainda não conectada** aos 7 construtores |
| **D** | Geração de pares DPO (auto-melhoria) | `~/.cache/swarm/curated_dpo_pairs.jsonl` | 🟡 **dir criado** — falta o módulo produtor |
| **E** | Hardening de alocador/cache | `~/.cache/swarm/scache.db` + `python3.15t` | 🟡 **dir criado** — `allocator.py`/`minimalloc.py` existem; `python3.15t` no PATH; falta hook S-Cache |

## Próximos passos (pendências)

1. **Diretriz C (fechar):** conectar `createMonomorphicNode` aos 7 construtores de `ConcreteNode` em `gemini-cli/packages/core/src/context/processors/*.ts` (hoje usam spread `...node` → polimorfismo V8). Requer `npm install` no gemini-cli para typecheck/testes.
2. **Diretriz D:** implementar produtor de pares em `swarm_sdk` escrevendo em `~/.cache/swarm/curated_dpo_pairs.jsonl`.
3. **Diretriz E:** ligar S-Cache SQLite WAL (`PRAGMA synchronous=NORMAL`, 64 MB page cache) e workers `python3.15t -X lazy_imports=all`.
4. **Diretriz B (deploy):** subir `mcp-xeon-server` no nó Xeon via systemd e registrar em `~/.gemini/settings.json` → `mcpServers`.

## mcp-xeon-server (Diretriz B)

```bash


cd mcp-xeon-server
npm install
npm run build && npm start   # SSE em http://0.0.0.0:8080/sse
```

Dependências: `@modelcontextprotocol/sdk`, `express`, `pg`, `playwright`.
Config via `.env` (ver `.env.example`): `PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE`, `PORT`.
Ferramentas expostas: `xeon_scrape_web`, `xeon_pgvector_query`, `xeon_sql_query`, `xeon_system_telemetry`.
