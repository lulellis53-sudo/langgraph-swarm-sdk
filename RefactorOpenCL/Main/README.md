# Main

Human-facing gather root for embeddings, vector stores, local binaries, and YAML. **Runtime imports stay `swarm_sdk.*`.** This folder is not a second uv project.

| Path | What it is |
| ---- | ---------- |
| [`embeddings/`](embeddings/) | Re-export of [`swarm_sdk.retrieval.embeddings`](../src/swarm_sdk/retrieval/embeddings.py) |
| [`vectorstore/`](vectorstore/) | Re-export of [`swarm_sdk.memory`](../src/swarm_sdk/memory/__init__.py) |
| [`config/`](config/) | Editable YAML. `swarm.yaml` and `model_registry.yaml` are symlinks to the packaged copies under `src/swarm_sdk/agents/config/` |
| [`Essentials/`](Essentials/) | Local llama.cpp dylibs and GGUF sidecars (gitignored) |
| [`../pyproject.toml`](../pyproject.toml) | Project metadata and extras — keep it at the repo root |

Activate the Intel Mac + Radeon profile with `SWARM_CONFIG_PATH=Main/config/swarm-bge-m3-radeon.yaml`.
