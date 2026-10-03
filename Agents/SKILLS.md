# Agent skills & coordination

Entry point for the swarm specialist catalog in this directory. Each `Name/`
folder is one persona: `AGENTS.md` is the behavioral role contract (the system
prompt), `agent.yaml` is the machine-readable manifest (model, think level,
token budget, tasks, capabilities). Validation: `uv run python -m swarm_sdk.agents.validate`.

## How personas become running agents

1. **Handoff swarm** (`swarm_sdk.core.swarm`) — every manifest whose
   `langgraph_node` is set becomes a LangGraph `create_agent` node via
   `langgraph_swarm.create_swarm`, fully meshed with handoff tools. Its system
   prompt is this folder's `AGENTS.md` contract, truncated to the manifest's
   `token_budget.max_prompt`; its model comes from the manifest (`model:` or
   think-level routing). Adding a specialist to the graph = create the folder +
   manifest and set `langgraph_node` to one of `researcher | coder | reviewer`.
2. **Plan orchestrator** (`swarm_sdk.orchestrator.spawn`) — the Orchestrator
   persona decomposes a goal into a `Plan` whose steps name any manifest here;
   workers execute one step each with their contract as system prompt.
   `langgraph_node` is not required for this path.
3. **Capabilities** — manifest `capabilities` gate runtime extras, e.g.
   `web_search` adds the WebSearch LangChain tools when
   `SWARM_ENABLE_WEBSEARCH_TOOLS=true` (`Settings.enable_websearch_tools`).

## Specialist catalog

| Persona | Role | Handoff node | Task ids |
| :--- | :--- | :--- | :--- |
| [Coder](Coder/AGENTS.md) | implement_changes | coder | implement_feature, implement_in_files, fix_regression, add_tests |
| [DataEngineer](DataEngineer/AGENTS.md) | data_pipeline_and_storage | - | pipeline_design, store_operations |
| [Debugger](Debugger/AGENTS.md) | root_cause_failures | - | reproduce_failure, identify_root_cause |
| [DeepResearch](DeepResearch/AGENTS.md) | deep_technical_research | - | argus_evidence_graph, hardware_runtime_benchmarks |
| [DevOps](DevOps/AGENTS.md) | ci_cd_and_environments | - | pipeline_green, environment_provision |
| [Documenter](Documenter/AGENTS.md) | maintain_documentation | - | sync_docs, generate_reference |
| [MLSpecialist](MLSpecialist/AGENTS.md) | model_selection_and_integration | - | model_evaluation, pipeline_integration |
| [ModelDelegate](ModelDelegate/AGENTS.md) | model_delegation | - | route_task, resolve_fallback, delegate_embedding, delegate_math |
| [Normalizer](Normalizer/AGENTS.md) | normalize_dedupe | - | normalize_dedupe |
| [Optimizer](Optimizer/AGENTS.md) | performance_tuning | - | profile_hotpath, apply_optimization |
| [Orchestrator](Orchestrator/AGENTS.md) | coordinate_swarm | - | decompose_goal, assign_tasks, merge_results |
| [Persister](Persister/AGENTS.md) | store_documents | - | store_documents |
| [Planner](Planner/AGENTS.md) | decompose_goals | - | decompose_goal, revise_plan |
| [RAG](RAG/AGENTS.md) | knowledge_retrieval | - | hybrid_retrieval, semantic_caching |
| [Refactor](Refactor/AGENTS.md) | safe_incremental_refactor | - | characterize, plan_refactor, execute_refactor |
| [Researcher](Researcher/AGENTS.md) | read_only_research | researcher | code_search, summarize_domain |
| [Reviewer](Reviewer/AGENTS.md) | review_changes | reviewer | diff_review, security_smell_check |
| [Security](Security/AGENTS.md) | security_review | - | secrets_audit, dependency_audit |
| [Tester](Tester/AGENTS.md) | write_and_run_tests | - | write_tests, run_gate |
| [TxtToCsv](TxtToCsv/AGENTS.md) | convert_text_files_to_csv | - | infer_format, convert |
| [WebFetch](WebFetch/AGENTS.md) | fetch_render | - | fetch_render |
| [Newsletter](Newsletter/AGENTS.md) | digest_generation | - | newsletter_mvp |

The `benchmark/` directory holds the primary test suite and evals; the
`code-review/`, `deep-research/`, and `math/` directories are mirrored prompt
catalogs consumed as reference material, not running agents.

## Coordination

Task assignment and status live in [coordination.yaml](coordination.yaml)
(`agents:` registry + `tasks:` board with `depends_on` / `status`). The
validator cross-checks it against the manifests: unknown assignees, unknown
task ids, and manifest name mismatches fail `python -m swarm_sdk.agents.validate`.
