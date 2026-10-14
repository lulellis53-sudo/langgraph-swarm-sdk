# Local Jupyter, Jupyter AI, and VS Code

> Research note — reviewed 2026-10-08 against the linked official documentation.
> This repository uses Python 3.14.8, `uv`, and a shared project `.venv`.

## Summary

Use the Swarm project environment for both notebook kernels and JupyterLab. The
project's `jupyter` extra includes `ipykernel`, Notebook, Jupyter AI, the
formatter, LSP and Python language server, and Git integration. The locked
Jupyter AI version is 3.1.3. The launcher at `scripts/jupyter.sh` runs
JupyterLab in the browser on `127.0.0.1:8888`, serves this `.Jupyter/` folder,
and leaves Jupyter Server's default token authentication enabled.

Jupyter AI 3 is a chat host, not a model or a bundled agent. Its current
architecture discovers installed ACP-compatible agents. Add an agent and its
required adapter separately; authenticate through that agent's normal local
sign-in flow. The optional Jupyternaut agent is experimental and uses a model
provider configured in Jupyter AI settings; a hosted provider generally needs
credentials, while local model support such as Ollama is another route.

For this machine, the recommended chat route is the supported Codex persona.
Jupyter AI needs the separate `@agentclientprotocol/codex-acp` adapter on
`PATH`; the Python extra does not install it. The current adapter release
could not resolve its Codex dependency from the configured npm registry, so
version 1.13.1 was installed; it includes Codex 0.156.1. Restart JupyterLab
and select the Codex persona in Chat. Choose ChatGPT sign-in if prompted; no
API key is added to this project.

## 1. Local architecture and data flow

```text
Browser (http://127.0.0.1:8888/lab)
    │ HTTP + Jupyter token cookie
    ▼
JupyterLab / Jupyter Server  ── Jupyter AI chat UI (optional)
    │                                  │ ACP
    ▼                                  ▼
ipykernel in project .venv      installed agent / model provider
    │
    └── notebook files under .Jupyter/
```

The server process and notebook kernel are separate processes. The server
serves files and manages kernels; the selected `ipykernel` executes notebook
cells. Jupyter AI's chat panel is an optional JupyterLab extension. VS Code's
notebook editor can instead run the same `.venv` kernel directly without
opening JupyterLab in a browser.

## 2. Install the project Jupyter environment

From the Swarm repository root:

```bash
uv sync --extra jupyter --extra dev
```

This installs the optional dependencies into the repository's existing `.venv`
and resolves against `uv.lock`. It also installs the Jupyter AI 3 host and the
three selected JupyterLab extensions. Do not create a second environment for
notebooks; the project guidance expects shared worktree environments. The
project constrains `cryptography` to a wheel build because local source builds
are unsuitable for this toolchain.

For repeatable notebooks, add durable packages to the relevant project extra
and update the lockfile. `%pip install package-name` inside a notebook is useful
for a temporary experiment, but it changes only the active kernel environment
and does not declare a project dependency.

## 3. Start JupyterLab in the local browser

Run:

```bash
./scripts/jupyter.sh
```

The script:

- starts JupyterLab through `uv` in the repository's `.venv`;
- listens only on loopback (`127.0.0.1`), so it is not exposed to the LAN;
- opens `.Jupyter/` as the browser-visible notebook root;
- uses port 8888 by default; set `JUPYTER_PORT` to choose another port;
- keeps the Jupyter Server token authentication default enabled; and
- lets JupyterLab open its tokenized local URL in the default browser.

The page is normally `http://127.0.0.1:8888/lab`. Use the tokenized URL
Jupyter prints in the launching terminal for the first login. The token is a
local server credential: do not paste it into source files, chat, or shared
logs. Once the browser has authenticated, it uses a session cookie.

Stop the server with **Ctrl+C** in its terminal. If port 8888 is occupied, use
for example:

```bash
JUPYTER_PORT=8890 ./scripts/jupyter.sh
```

Do not disable token/password authentication or change the bind address to
`0.0.0.0` for this local workflow. Access to the server permits arbitrary code
execution in the user account. The `.Jupyter/` root also keeps the browser file
listing scoped away from repository files such as `.env`.

To start manually, the equivalent shape is:

```bash
uv run --extra jupyter jupyter lab \
  --ip=127.0.0.1 \
  --port=8888 \
  --ServerApp.root_dir="$PWD/.Jupyter"
```

JupyterLab opens a browser by default. To prevent auto-open and use the local
URL yourself, add `--ServerApp.open_browser=False`; the server still prints its
tokenized URL in the terminal.

## 4. Use notebooks in VS Code

The workspace recommends Microsoft's Python and Jupyter extensions. Open
`codeworkspace/swarm.code-workspace`, open a notebook under `.Jupyter/`, then
use **Select Kernel** and select the Python environment at
`${workspaceFolder:SDK (integration)}/.venv/bin/python`. Run a small cell:

```python
import sys

print(sys.executable)
```

The printed executable should be the repository `.venv` Python. If no kernel is
listed, first run `uv sync --extra jupyter --extra dev`, then reload VS Code
and select the interpreter again. A manually registered user kernelspec is
optional; selecting the existing project interpreter is simpler and avoids
installing a kernelspec outside the repo.

The browser workflow and VS Code workflow may use the same kernel environment,
but they are separate Jupyter frontends. Avoid opening the same notebook in
both and executing stateful cells concurrently unless that is intentional.

## 5. Configure and use Jupyter AI

### 5.1 Understand the components

Jupyter AI 3 provides the JupyterLab chat interface and manages personas. An
ACP agent is the assistant implementation, and a model/provider is selected by
that agent. Jupyter AI does not include an ACP agent by default. A visible chat
panel alone does not mean a model is configured.

1. Install one supported agent and any adapter package required by the current
   [Jupyter AI getting-started guide](https://jupyter-ai.readthedocs.io/en/latest/getting-started.html).
2. Authenticate using that agent's own CLI or browser sign-in flow, as its
   documentation describes.
3. Restart JupyterLab with `./scripts/jupyter.sh` so it discovers the installed
   agent.
4. In JupyterLab, open the **Chat** panel, create a chat, and choose the
   available persona. Wait for the agent to initialize and expose its model and
   permission choices.
5. Begin with read-only assistance. Grant tool permissions deliberately before
   allowing notebook edits, shell commands, or filesystem writes.

The project's `jupyter` extra provides the Jupyter AI host only. It does not
install an ACP agent adapter or configure a provider credential. Use the
agent's existing sign-in mechanism where possible; never put tokens in a
notebook, `.Jupyter` workspace file, or source-controlled configuration.

#### Codex ACP setup

The npm ACP adapter is a separate global install. The current working
installation is pinned to 1.13.1 because the latest release requires a Codex
package version not available from the configured npm registry. Run JupyterLab
from this project so its inherited `PATH` can discover the adapter:

```bash
npm install -g @agentclientprotocol/codex-acp@1.13.1
./scripts/jupyter.sh
```

The adapter supports ChatGPT sign-in, which does not require adding an API key
to the project. In JupyterLab, open **Chat**, create a chat, and select
**Codex**. Review tool permissions before allowing the agent to edit files or
run commands. If the persona is not listed, check `command -v codex-acp` and
restart the server.

### 5.2 Jupyternaut option

Jupyternaut is an optional, experimental Jupyter AI agent. It supports a
provider/model picker in **Settings → Jupyternaut Settings**. A hosted model
provider normally requires its own provider credentials and dependencies. The
official Jupyternaut docs also cover local Ollama models; Ollama must be
installed, the chosen model pulled, and its local server running. This route
avoids embedding a hosted-provider key in a notebook, but it has separate
software and resource requirements.

Do not install Jupyternaut into the shared project environment without first
adding it deliberately to the `jupyter` extra and regenerating `uv.lock`.
The optional package is not needed just to use the Jupyter AI chat host with an
ACP agent.

### 5.3 Notebook AI magics (optional)

The `%%ai` and `%ai` notebook magics are a separate optional package,
`jupyter-ai-magic-commands`; they are not required for the chat panel. If this
workflow is wanted, add the package as a declared optional project dependency,
install it in the same kernel environment, then load it in a notebook:

```python
%load_ext jupyter_ai_magic_commands
%ai list
```

Provider/model identifiers and configuration syntax are documented in the
[Jupyter AI magic commands guide](https://jupyter-ai.readthedocs.io/en/latest/users/magic_commands/index.html).
Magics still require a configured model/agent and authentication. Do not put
credential values in notebook cells because notebooks save cell source and
outputs.

### 5.4 Configure the selected JupyterLab extensions

#### Ruff formatter

The formatter extension has a Ruff command, and Ruff is already part of the
development dependencies. In JupyterLab open **Settings → Advanced Settings
Editor → JupyterLab Code Formatter** and set this in User Preferences:

    {
      "preferences": {
        "default_formatter": {
          "python": "ruff"
        }
      }
    }

Use the formatter command for the focused cell or the format-all command for
the notebook. Format-on-save stays off by default. The extension does not read
Ruff's settings from pyproject.toml, so review formatting changes before saving.

#### Python language server

JupyterLab LSP supplies browser-editor integration; python-lsp-server supplies
the Python language server. Restart JupyterLab after installing the packages.
The server should be auto-detected and provide diagnostics, completion, hover,
go-to-definition, and rename features. If diagnostics are noisy, configure the
language server or disable duplicate linters; Ruff remains the formatter and
project lint authority.

#### Git panel

JupyterLab Git adds a Git tab in the sidebar. The server starts from the repo
root and serves .Jupyter/, so the extension can find the parent repository.
Use it to review status and diffs or stage changes. Commit, reset, revert, push,
and pull actions modify the checkout or remote; review the target and diff
before using them. Remote operations use the repository's existing Git
credential setup.

## 6. Configuration and security boundaries

- `pyproject.toml` and `uv.lock` define packages; `scripts/jupyter.sh` defines
  loopback binding, port, and served root.
- VS Code settings live in `codeworkspace/swarm.code-workspace`; they select
  local Jupyter behavior but do not configure Jupyter Server authentication.
- Jupyter Server's generated token authentication is enabled by default. Do
  not set the token or password to an empty value.
- Keep the process bound to `127.0.0.1`. Do not enable permissive CORS or
  `allow_origin='*'` for a local-only workflow.
- Keep API keys and agent credentials in the agent/provider's supported local
  credential store or environment mechanism. Never commit them or save them in
  notebooks, `.env.example`, or workspace JSON.
- Jupyter AI agents can have tools that read/write files and execute commands.
  Review permission prompts; the server's local authentication is not a
  sandbox for notebook code.

## 7. Troubleshooting

| Symptom | Check |
| --- | --- |
| `jupyter: command not found` | Run `uv sync --extra jupyter --extra dev` from the repo root, then retry the script. |
| Browser cannot connect | Confirm the server process is still running and use its printed URL; check whether `JUPYTER_PORT` selected a different port. |
| Port already in use | Start with `JUPYTER_PORT=8890 ./scripts/jupyter.sh`. |
| No Python kernel in VS Code | Select the project's `.venv` interpreter, then reload after installing the Jupyter extra. |
| Jupyter AI chat is missing | Confirm the project environment has Jupyter AI installed and restart the server. |
| Chat appears but no persona is available | Install a supported ACP agent and its required adapter; Jupyter AI ships no agent by default. |
| Agent is available but cannot authenticate | Use the agent's own CLI/browser login and restart the JupyterLab server. |
| Notebook import cannot find `swarm_sdk` | Run the notebook under the project `.venv`; the project package is installed editable in that environment. |

## 8. Machine-specific state observed

- The project lock currently resolves `jupyter-ai` 3.1.3, `jupyterlab` 4.6.4,
  and `jupyter-server` 2.21.1.
- The existing `scripts/jupyter.sh` had pointed at a root `notebooks/` directory
  that does not exist. It now serves `.Jupyter/` and binds to loopback.
- The project `.venv` exists, but the Jupyter distributions were not installed
  in it at the time of inspection. The lock file contains the Jupyter extra;
  installation remains the explicit `uv sync` step above.

## 9. Official references

1. [JupyterLab: Starting JupyterLab](https://jupyterlab.readthedocs.io/en/stable/getting_started/starting.html) — launch behavior, browser URL, and notebook root.
2. [Jupyter Server: Security](https://jupyter-server.readthedocs.io/en/stable/operators/security.html) — default token authentication and local server security.
3. [Jupyter AI: Getting Started](https://jupyter-ai.readthedocs.io/en/latest/getting-started.html) — host installation, supported agents, and chat workflow.
4. [Jupyter AI: User Guide](https://jupyter-ai.readthedocs.io/en/latest/users/index.html) — chat personas, model selection, tools, and permissions.
5. [Jupyter AI: Jupyternaut](https://jupyter-ai.readthedocs.io/en/latest/users/jupyternaut/index.html) — optional agent, providers, and local Ollama support.
6. [Jupyter AI: Magic Commands](https://jupyter-ai.readthedocs.io/en/latest/users/magic_commands/index.html) — optional notebook magics.
7. [VS Code: Jupyter Notebooks](https://code.visualstudio.com/docs/datascience/jupyter-notebooks) — local notebook and server workflows.
8. [VS Code: Jupyter Kernel Management](https://code.visualstudio.com/docs/datascience/jupyter-kernel-management) — selecting Python environments and existing servers.
9. [JupyterLab Git](https://github.com/jupyterlab/jupyterlab-git) — JupyterLab 4 compatibility and Git panel.
10. [JupyterLab LSP](https://jupyterlab-lsp.readthedocs.io/en/latest/Installation.html) — browser editor integration and Python language server.
11. [JupyterLab Code Formatter configuration](https://jupyterlab-code-formatter.readthedocs.io/configuration.html) — formatter preferences.
