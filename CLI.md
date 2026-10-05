# CLI & Tooling Reference — LangGraph Swarm SDK

A comprehensive, operational guide to the command-line interfaces, modern Unix toolchains, service entrypoints, and keybinding configurations for the LangGraph Swarm SDK.

---

## Table of Contents

1. [Overview & Modern Unix CLI Toolchain Mandate](#1-overview--modern-unix-cli-toolchain-mandate)
2. [`low-swarm`: Autonomous Synthesis Swarm CLI](#2-low-swarm-autonomous-synthesis-swarm-cli)
   - [2.1 `low-swarm run`](#21-low-swarm-run)
   - [2.2 `low-swarm vault`](#22-low-swarm-vault)
   - [2.3 `low-swarm ingest`](#23-low-swarm-ingest)
   - [2.4 `low-swarm doctor`](#24-low-swarm-doctor)
3. [`swarm-vault`: Keychain Credential Manager](#3-swarm-vault-keychain-credential-manager)
4. [Serving & Orchestration Entrypoints](#4-serving--orchestration-entrypoints)
   - [4.1 `swarm-api` (HTTP / SSE REST Service)](#41-swarm-api-http--sse-rest-service)
   - [4.2 `swarm-grpc` (High-Throughput gRPC Service)](#42-swarm-grpc-high-throughput-grpc-service)
   - [4.3 `langgraph-cli` (LangGraph Server Deployment)](#43-langgraph-cli-langgraph-server-deployment)
5. [CLI Keys, Shortcuts & Keybinding Recommendations](#5-cli-keys-shortcuts--keybinding-recommendations)
   - [5.1 Shell / Terminal Keybindings (Zsh / FZF / Ghostty)](#51-shell--terminal-keybindings-zsh--fzf--ghostty)
   - [5.2 Cursor & VS Code Slash Commands & Keybindings](#52-cursor--vs-code-slash-commands--keybindings)
   - [5.3 Vault Secret Keys Registry (Supported Providers)](#53-vault-secret-keys-registry-supported-providers)
6. [Quality Gate Verification Protocol](#6-quality-gate-verification-protocol)

---

## 1. Overview & Modern Unix CLI Toolchain Mandate

In accordance with repository guidelines (`GEMINI.md` and `AGENTS.md`), **always prioritize modern, high-performance Unix CLI tools** over legacy BSD/GNU utilities. Never deploy monolithic scripts or multi-step agent frameworks when a fast CLI one-liner solves the problem directly.

### Verified Toolchain Inventory (Active Host)

All modern CLI tools are installed and verified on this machine:

| Domain / Task | Fast CLI Tool (Mandatory) | Installed Absolute Path | Legacy Tool (Deprecated) | Capabilities & Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **Code & Content Search** | `rg` (ripgrep) | `/Users/usuario/.cargo/bin/rg` | `grep`, `egrep` | Multi-threaded SIMD regex, memory-mapped I/O, ultra-fast traversal. |
| **File Display & Paging** | `bat` | `/Users/usuario/.cargo/bin/bat` | `cat`, `more`, `less` | Automatic syntax highlighting, line numbers, git status indicators. |
| **File & Path Discovery** | `fd` | `/Users/usuario/.kimi-code/bin/fd` | `find` | Parallel directory traversal, smart-case regex, ignores `.git`. |
| **Stream / String Replace**| `sd` | `/usr/local/bin/sd` | `sed` | Rust regex engine, clean intuitive `sd 'find' 'replace'` syntax. |
| **Field Extraction** | `choose` | `/usr/local/bin/choose` | `awk` | Fast, zero-overhead human-friendly field cutting and slicing. |
| **Directory Listing** | `eza` | `/Users/usuario/.cargo/bin/eza` | `ls` | Tree view, metadata, Unix file permissions, Git file statuses. |
| **System & Process Monitor**| `btm` (bottom) | `/Users/usuario/.cargo/bin/btm` | `top`, `htop` | Terminal graphical resource monitor for CPU, memory, processes. |
| **Process Inspection** | `procs` | `/usr/local/bin/procs` | `ps` | Structured, type-highlighted process viewer with tree display. |
| **Disk Tree Usage** | `dust` | `/Users/usuario/.cargo/bin/dust` | `du` | Interactive graphical terminal tree visualizing disk consumption. |
| **Disk Free / Mounts** | `duf` | `/usr/local/bin/duf` | `df` | Clean, modern terminal table of block devices and mount points. |
| **Git Diffs & Patches** | `delta` | `/Users/usuario/.pixi/bin/delta` | `diff` | Word-level diffing, syntax-highlighted side-by-side git pagers. |
| **JSON Stream Processing** | `jq` | `/usr/bin/jq` | `python -m json.tool` | High-throughput native JSON parsing, filtering, and slicing. |
| **CLI Benchmarking** | `hyperfine` | `/Users/usuario/.cargo/bin/hyperfine` | `time` loops | Statistical warmup runs, multi-command comparative benchmarking. |

---

## 2. `low-swarm`: Autonomous Synthesis Swarm CLI

`low-swarm` is the central command-line interface for the low-resource autonomous code synthesis engine, vector ingestion, vault management, and host diagnostics.

Entrypoint script: `uv run low-swarm <command> [options]`

```text
usage: low-swarm [-h] {run,vault,ingest,doctor} ...

Low-Resource Autonomous Code Synthesis Swarm CLI

positional arguments:
  {run,vault,ingest,doctor}
    run                 Run autonomous code synthesis or refactoring task
    vault               Manage macOS Keychain credentials
    ingest              Ingest Markdown files into FAISS vector database
    doctor              Inspect host invariants, SIMD, and CLI tooling
```

---

### 2.1 `low-swarm run`

Executes the autonomous code synthesis state machine with Jev safety verification, Lifeguard AST auditing, and diff patch generation.

```bash
uv run low-swarm run "Task description" [OPTIONS]
```

#### Supported Arguments & Flags:
- `task` (positional, required): Natural language description of synthesis or refactoring task.
- `--files [FILE ...]` (optional): Explicit target file paths to synthesize, read, or modify.
- `--tier {auto,flash_lite,pro}` (default: `auto`): Model intelligence tier selected by the Jev routing gate.
- `--profile`: Captures wall-clock latency (ms), process CPU time (ms), and resident memory consumption (RSS in GB).
- `--apply`: Automatically writes synthesized code patches directly to target files upon passing all audit gates.
- `--verbose`: Emits detailed telemetry, including context chunk counts and state iteration steps.

#### Execution State Machine Workflow:
1. **Host Guard**: Verifies process RSS does not exceed the 13.6 GB hardware safety ceiling.
2. **Jev Safety Gate**: Computes safety scores; blocks prompt injections or destructive disk commands.
3. **Synthesis Engine**: Generates targeted Python implementations or diff patches.
4. **Lifeguard AST Audit**: Statically audits synthesized code for prohibited constructs (`os.system`, raw `subprocess`, unshielded infinite loops).
5. **Output Delivery**: Pretty-prints formatted summary tables and syntax-highlighted diffs using `rich` (with seamless `PlainConsole` fallback).

#### Example Invocations:

```bash
# Basic code synthesis task
uv run low-swarm run "Implement pure-Python LRU cache with TTL expiration"

# Refactor target files with profiling telemetry
uv run low-swarm run "Optimize matrix vector multiplications" \
  --files src/swarm_sdk/gpu/opencl_math.py \
  --profile --verbose

# Apply synthesized changes directly to disk
uv run low-swarm run "Add docstrings and type annotations to helper.py" \
  --files helper.py \
  --apply
```

---

### 2.2 `low-swarm vault`

Manages credentials securely via macOS Keychain without exposing values in process tables or shell logs.

```bash
# Store an API key into macOS Keychain
uv run low-swarm vault set --service OPENAI_API_KEY --key "sk-..."

# Store with shorthand service name (auto-normalized to uppercase _API_KEY)
uv run low-swarm vault set --service openai --key "sk-..."
uv run low-swarm vault set --service jev --key "jev-..."

# Retrieve an API key
uv run low-swarm vault get --service OPENAI_API_KEY

# Inspect vault status (displays CONFIGURED vs MISSING without leaking values)
uv run low-swarm vault status
```

---

### 2.3 `low-swarm ingest`

Ingests Markdown documentation, technical guides, or source modules into a FAISS vector index with metadata chunking.

```bash
uv run low-swarm ingest --source <SOURCE_PATH> --output <OUTPUT_DIR>
```

#### Example:
```bash
uv run low-swarm ingest --source ./docs --output ./var/rag_index
```
Produces `chunks.json`, `meta.json`, and the vectorized index files in the target directory.

---

### 2.4 `low-swarm doctor`

Inspects host hardware invariants, Coffee Lake-H microarchitecture limits, active SIMD extensions, RAM hard ceilings, and modern Unix CLI tool presence.

```bash
uv run low-swarm doctor
```

#### Verified Output Profile:
- **CPU Architecture**: `x86_64` (Intel Core i7-9750H, 6 cores / 12 threads)
- **Supported SIMD**: `AVX2`, `FMA`, `SSE4.2`
- **Prohibited SIMD**: `AVX-512` (strictly prohibited; avoids illegal instruction crashes)
- **RAM Hard Ceiling**: `< 13.6 GB` (protects host macOS 16 GB envelope)
- **Subagent Concurrency**: Enforced cap of `3` parallel workers
- **CLI Tools**: Checks availability of `rg`, `bat`, `fd`, `sd`, `choose`, `eza`

---

## 3. `swarm-vault`: Keychain Credential Manager

The dedicated secret management tool `swarm-vault` provides a secure interface for storing, reading, and auditing credentials in the macOS Keychain under the service prefix `swarm/<NAME>`.

Entrypoint script: `uv run swarm-vault {set|get|status|import}`

### Security Invariants:
1. **Zero Argument Exposure**: `swarm-vault set NAME` prompts via `getpass.getpass()` and transfers keys directly to `/usr/bin/security -i` via stdin. Keys are never passed on `argv`.
2. **Zero Log Leaks**: Secrets are never written to logfiles, stdout, or exception messages. Errors reference only the secret name.
3. **Lookup Hierarchy**:
   ```text
   Process Environment (os.environ)
     └──> macOS Keychain (swarm/<NAME>)
            └──> Legacy gitignored file (~/.env)
   ```

### Command Usage:

```bash
# 1. Set a secret (prompts for value securely without echo)
uv run swarm-vault set OPENAI_API_KEY

# 2. Check presence of known keys without displaying values
uv run swarm-vault status

# 3. Check specific keys
uv run swarm-vault status OPENAI_API_KEY ANTHROPIC_API_KEY MEM0_API_KEY

# 4. Bulk import secrets from a protected file (KEY=VALUE or KEY,VALUE format)
uv run swarm-vault import ~/.env.secrets
```

---

## 4. Serving & Orchestration Entrypoints

The SDK provides three production serving entrypoints configured via environment variables (prefixed with `SWARM_`):

### 4.1 `swarm-api` (HTTP / SSE REST Service)

FastAPI-powered REST and Server-Sent Events (SSE) streaming server running over `uvicorn` and `uvloop`.

- **Entrypoint**: `uv run swarm-api`
- **Default Address**: `http://127.0.0.1:8000`
- **Key Environment Variables**:
  - `SWARM_API_HOST`: Bind address (default: `127.0.0.1`)
  - `SWARM_API_PORT`: Bind port (default: `8000`)
  - `SWARM_ROUTER_MODEL`: Model routing definition (default: `openai:gpt-4o-mini`)
  - `SWARM_SPECIALIST_MODEL`: Specialist worker model (default: `openai:gpt-4o`)
  - `SWARM_MEMORY_BACKEND`: Storage backend (`sqlite-vec`, `faiss`, `qdrant`, `opencl`, `mem0`)

```bash
# Launch HTTP API on custom port
SWARM_API_PORT=8080 uv run swarm-api
```

---

### 4.2 `swarm-grpc` (High-Throughput gRPC Service)

High-performance gRPC protobuf service for inter-agent RPC communication.

- **Entrypoint**: `uv run swarm-grpc`
- **Default Port**: `50051`
- **Key Environment Variable**:
  - `SWARM_GRPC_PORT`: gRPC listening port (default: `50051`)
- **Protobuf Compilation**:
  If `src/swarm_sdk/pb/swarm.proto` is modified, regenerate Python stubs using:
  ```bash
  uv run python -m swarm_sdk.pb
  ```

```bash
# Launch gRPC service
SWARM_GRPC_PORT=50055 uv run swarm-grpc
```

---

### 4.3 `langgraph-cli` (LangGraph Server Deployment)

Runs the multi-agent graph server defined in `langgraph.json`.

- **Graphs Served**:
  - `swarm`: Multi-agent handoff graph (`src/swarm_sdk/server/graphs.py:make_swarm_graph`)
  - `plan`: Spawn-and-wave orchestrator (`src/swarm_sdk/server/graphs.py:make_plan_graph`)
- **Invocation**:
  ```bash
  uv run langgraph up
  ```
- **Client Delegation**:
  Set `SWARM_SERVER_URL=http://127.0.0.1:2024` to delegate swarm runs from `SwarmSDK.run` to the external LangGraph server.

---

## 5. CLI Keys, Shortcuts & Keybinding Recommendations

To maximize operational throughput and minimize keystroke overhead, use the following keybinding and shortcut recommendations:

### 5.1 Shell / Terminal Keybindings (Zsh / FZF / Ghostty)

Add these bindings to your interactive `~/.zshrc` or shell profile:

#### Recommended Zsh Aliases:
```zsh
# Fast modern CLI tool mappings
alias ls="eza --icons --group-directories-first"
alias ll="eza -lh --icons --git"
alias tree="eza --tree --level=3 --icons"
alias cat="bat --paging=never"
alias grep="rg"
alias find="fd"
alias top="btm"
alias ps="procs"
alias du="dust"
alias df="duf"
alias diff="delta"

# Swarm SDK core shortcuts
alias swarm="uv run low-swarm"
alias swarm-run="uv run low-swarm run"
alias doctor="uv run low-swarm doctor"
alias vault="uv run swarm-vault"
alias gate="uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 pytest Agents/benchmark -q"
```

#### Zsh Interactive Widgets & Keybindings:
```zsh
# Trigger low-swarm doctor with Ctrl+X Ctrl+D
doctor-widget() {
  echo ""
  uv run low-swarm doctor
  zle reset-prompt
}
zle -N doctor-widget
bindkey '^X^D' doctor-widget

# Trigger full quality gate with Ctrl+X Ctrl+G
gate-widget() {
  echo ""
  uv run --extra dev pytest tests/test_cli.py -q
  zle reset-prompt
}
zle -N gate-widget
bindkey '^X^G' gate-widget
```

#### Ghostty Terminal Configuration (`~/.config/ghostty/config`):
```text
keybind = super+shift+d=new_split:right
keybind = super+shift+e=new_split:down
keybind = super+k=clear_screen
keybind = super+r=reload_config
```

---

### 5.2 Cursor & VS Code Slash Commands & Keybindings

#### Recommended Keybindings (`keybindings.json`):
```json
[
  {
    "key": "cmd+shift+d",
    "command": "workbench.action.terminal.sendSequence",
    "args": { "text": "uv run low-swarm doctor\u000D" }
  },
  {
    "key": "cmd+shift+t",
    "command": "workbench.action.terminal.sendSequence",
    "args": { "text": "uv run --extra dev pytest tests/test_cli.py -q\u000D" }
  },
  {
    "key": "cmd+shift+v",
    "command": "workbench.action.terminal.sendSequence",
    "args": { "text": "uv run swarm-vault status\u000D" }
  }
]
```

#### Slash Commands (`.cursor/commands/`):
- `/sql-pro`: Executes the offline SQL Pro benchmark suite (`uv run python -m benchmark.sql_pro.run`).
- `/doctor`: Runs the host architecture and invariant diagnostics (`uv run low-swarm doctor`).
- `/quality-gate`: Runs the comprehensive test suite, Ruff, Ty, and agent manifest validation.
- `/vault`: Inspects Keychain vault credential coverage without leaking secrets.

---

### 5.3 Vault Secret Keys Registry (Supported Providers)

The repository registry actively references 35 credentials across `swarm.yaml`, `model_registry.yaml`, and `swarm_sdk.vault`:

| Provider / Model Family | Environment Variable Name | Secret Storage Command | Purpose / Route |
| :--- | :--- | :--- | :--- |
| **OpenAI** | `OPENAI_API_KEY` | `uv run swarm-vault set OPENAI_API_KEY` | GPT-4o, GPT-4o-mini router models |
| **Anthropic** | `ANTHROPIC_API_KEY` | `uv run swarm-vault set ANTHROPIC_API_KEY` | Claude 3.5 Sonnet, Claude 3.7 Sonnet |
| **Google Gemini** | `GEMINI_API_KEY` | `uv run swarm-vault set GEMINI_API_KEY` | Gemini 3.8 Flash. `GOOGLE_API_KEY` is accepted when the Gemini names are unset |
| **Groq** | `GROQ_API_KEY` | `uv run swarm-vault set GROQ_API_KEY` | Llama-3.3-70b-versatile, DeepSeek |
| **Groq Backup** | `GROQ_API_KEY_2` | `uv run swarm-vault set GROQ_API_KEY_2` | Failover pool for Groq endpoints |
| **Cohere Primary** | `COHERE_API_KEY_1` | `uv run swarm-vault set COHERE_API_KEY_1` | Command-R, Cohere rerankers |
| **Cohere Secondary** | `COHERE_API_KEY_2` | `uv run swarm-vault set COHERE_API_KEY_2` | Failover pool for Cohere rerankers |
| **Mistral Primary** | `MISTRAL_API_KEY_1` | `uv run swarm-vault set MISTRAL_API_KEY_1` | Mistral Large, Codestral |
| **Mistral Secondary** | `MISTRAL_API_KEY_2` | `uv run swarm-vault set MISTRAL_API_KEY_2` | Failover pool for Mistral API |
| **Tavily Search** | `TAVILY_API_KEY` | `uv run swarm-vault set TAVILY_API_KEY` | WebSearch Tavily searcher |
| **Brave Search** | `BRAVE_API_KEY` | `uv run swarm-vault set BRAVE_API_KEY` | WebSearch Brave API crawler |
| **Jina Search** | `JINA_API_KEY` | `uv run swarm-vault set JINA_API_KEY` | WebSearch `s.jina.ai`. Embeddings stay on `JINA_BASE_URL` (`api.jina.ai/v1`) |
| **Poolside** | `POOLSIDE_API_KEY` | `uv run swarm-vault set POOLSIDE_API_KEY` | Laguna S 2.1 at `https://inference.poolside.ai/v1` |
| **Exa Search** | `EXA_API_KEY` | `uv run swarm-vault set EXA_API_KEY` | WebSearch Exa neural search |
| **Mem0 Platform** | `MEM0_API_KEY` | `uv run swarm-vault set MEM0_API_KEY` | Long-term user/agent memory |
| **Jev** | `JEV_API_KEY` | `uv run swarm-vault set JEV_API_KEY` | TypeSafe `POST /v1/systemone` on `JEV_BASE_URL` (`api.typesafe.ai`), model `jev-latest` |
| **xAI** | `XAI_API_KEY` | `uv run swarm-vault set XAI_API_KEY` | Grok-beta / Grok-2 |
| **Fireworks AI** | `FIREWORKS_API_KEY` | `uv run swarm-vault set FIREWORKS_API_KEY` | Serverless open-weights models |
| **OpenRouter** | `OPENROUTER_API_KEY` | `uv run swarm-vault set OPENROUTER_API_KEY` | Unified router endpoint |
| **SambaNova** | `SAMBANOVA_API_KEY` | `uv run swarm-vault set SAMBANOVA_API_KEY` | Ultra-fast Llama-3.1 inference |
| **Alibaba / DashScope** | `ALIBABA_API_KEY` | `uv run swarm-vault set ALIBABA_API_KEY` | Qwen-2.5-Coder models |
| **MiniMax** | `MINIMAX_API_KEY` | `uv run swarm-vault set MINIMAX_API_KEY` | MiniMax API authentication |
| **MiniMax URL** | `MINIMAX_BASE_URL` | `uv run swarm-vault set MINIMAX_BASE_URL` | Custom base endpoint URL |
| **Xiaomi MiMo** | `MIMO_API_KEY` | `uv run swarm-vault set MIMO_API_KEY` | MiMo model API token |
| **Xiaomi MiMo URL** | `MIMO_BASE_URL` | `uv run swarm-vault set MIMO_BASE_URL` | Custom base endpoint URL |
| **Moonshot / Kimi** | `KIMI_CODE_PLAN_API_KEY` | `uv run swarm-vault set KIMI_CODE_PLAN_API_KEY` | Kimi / Moonshot planner |
| **Moonshot URL** | `MOONSHOT_BASE_URL` | `uv run swarm-vault set MOONSHOT_BASE_URL` | Kimi base endpoint URL |
| **Claude Code** | `CLAUDE_CODE_API_KEY` | `uv run swarm-vault set CLAUDE_CODE_API_KEY` | Claude Code CLI integration |
| **Codex OAuth** | `CODEX_OAUTH_TOKEN` | `uv run swarm-vault set CODEX_OAUTH_TOKEN` | OpenAI Codex OAuth token |
| **NVIDIA NIM** | `NVIDIA_API_KEY` | `uv run swarm-vault set NVIDIA_API_KEY` | NVIDIA NIM microservices API |
| **NVIDIA URL** | `NVIDIA_BASE_URL` | `uv run swarm-vault set NVIDIA_BASE_URL` | Custom NIM microservice endpoint |
| **Ollama Local URL** | `OLLAMA_BASE_URL` | `uv run swarm-vault set OLLAMA_BASE_URL` | Local Ollama endpoint (e.g. `http://localhost:11434`) |
| **Ollama Failover URL**| `OLLAMA_2_BASE_URL` | `uv run swarm-vault set OLLAMA_2_BASE_URL` | Secondary Ollama node URL |
| **Ollama Cloud** | `OLLAMA_CLOUD_API_KEY` | `uv run swarm-vault set OLLAMA_CLOUD_API_KEY` | Managed Ollama Cloud token |
| **Ollama Cloud URL** | `OLLAMA_CLOUD_BASE_URL` | `uv run swarm-vault set OLLAMA_CLOUD_BASE_URL` | Managed Ollama Cloud endpoint |
| **Z.ai (Zhipu)** | `ZHIPU_API_KEY` | `uv run swarm-vault set ZHIPU_API_KEY` | GLM 5.2 API key, not OAuth. `ZAI_API_KEY` is accepted when this name is unset |
| **ZAI Base URL** | `ZAI_BASE_URL` | `uv run swarm-vault set ZAI_BASE_URL` | GLM base endpoint URL |
| **Atlas Cloud** | `ATLASCLOUD_API_KEY` | `uv run swarm-vault set ATLASCLOUD_API_KEY` | Free chat model `dots-studio/dots-3-note-prev-free` ($0/$0 on 2026-10-05). No web-search tool |
| **Google API key** | `GOOGLE_API_KEY` | `uv run swarm-vault set GOOGLE_API_KEY` | Alternate name for Gemini routes and Google Search grounding |

---

## 6. Quality Gate Verification Protocol

Run the quality gate sequence before opening pull requests or claiming task completion:

```bash
# Step 1: Narrow unit tests for CLI
uv run --extra dev pytest tests/test_cli.py -q --tb=short

# Step 2: Full repository benchmark suite
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 pytest Agents/benchmark -q

# Step 3: Lint check
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ruff check src Agents/benchmark Main

# Step 4: Type verification
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ty check src Agents/benchmark Main

# Step 5: Agent manifests validation
uv run python -m swarm_sdk.agents.validate
```
