# Agent Tools Specification: ShellMaster

> **Authoritative Specification**: Tooling catalog, API endpoints, style guides, and validation engines for `ShellMaster`.

---

## 1. Shell Scripting & Style Guides

`ShellMaster` adheres strictly to established production shell scripting standards:

| Reference Guide | URL Documentation | Core Principles & Application |
| :--- | :--- | :--- |
| **Advanced Bash-Scripting Guide (Hangar118 / SDF)** | [Hangar118 Bash Guide](https://hangar118.sdf.org/p/bash-scripting-guide/) | **Primary Shell Style Prompt Guide**: Parameter substitution (`${var:-default}`, `${var//pat/rep}`), string manipulation, arithmetic evaluation (`(( ... ))`), subshells, process substitution (`<(...)`), array handling, I/O redirection, and gotchas prevention. |
| **Google Shell Style Guide** | [Google Shell Guide](https://google.github.io/styleguide/shellguide.html) | Formatting, 2-space indentation, function definitions (`my_func() { ... }`), `main "$@"`, environment safety, and naming conventions (`snake_case` functions, `UPPERCASE` constants). |
| **CLITOOLS System Catalog** | `~/Desktop/Documentos/CLITOOLS.md` | Modern Unix utilities prioritization over legacy BSD/GNU tools. |

---

## 2. Shell Engineering Standards & Idioms

### 2.1 Essential Script Header

Every production shell script authored or modified by `ShellMaster` must start with strict safety flags:

```bash
#!/usr/bin/env bash
# Description: Purpose of script
# Authoritative Guide: https://hangar118.sdf.org/p/bash-scripting-guide/

set -euo pipefail
IFS=$'\n\t'
```

For zsh scripts:
```zsh
#!/usr/bin/env zsh
set -euo pipefail
```

### 2.2 Quoting & Parameter Expansion Rules (Hangar118 Standard)

- **Always Quote Variables**: Always wrap variables in double quotes (`"${variable}"`) to prevent word splitting and glob expansion.
- **Safe Parameter Defaults**: Use parameter expansion for optional variables:
  ```bash
  output_dir="${1:-/tmp/output}"
  prefix="${APP_PREFIX:-default_prefix}"
  ```
- **Arithmetic Evaluation**: Prefer double parentheses over legacy `expr` or `let`:
  ```bash
  (( count = count + 1 ))
  if (( total >= threshold )); then ...
  ```
- **String Manipulation**: Use built-in parameter expansion over external `sed`/`awk` processes for performance:
  ```bash
  filename="${path##*/}"     # basename
  dirname="${path%/*}"       # dirname
  extension="${filename##*.}" # file extension
  ```

---

## 3. Modern CLI Tooling Catalog

`ShellMaster` prioritizes the following installed modern CLI tools located in `/Users/usuario/.cargo/bin`, `/usr/local/bin`, and `/Users/usuario/.local/bin`:

| Tool | Category | Modern Utility | Legacy Counterpart |
| :--- | :--- | :--- | :--- |
| **`rg`** | Text search | Ripgrep (gitignore-aware, multi-threaded) | `grep`, `egrep` |
| **`fd`** | File finding | Fast filesystem traversal | `find` |
| **`bat`** | File inspection | Syntax highlighting + line numbers | `cat`, `more` |
| **`eza`** | Directory listing | Git status inline, tree view | `ls` |
| **`sd`** | Text replacement | Intuitive regex find & replace | `sed` |
| **`choose`** | Column slicing | 0-indexed human-friendly slicing | `awk '{print $N}'`, `cut` |
| **`dust` / `duf`** | Disk usage | Interactive visual tree / disk free | `du`, `df` |
| **`btm`** | Process monitoring | Bottom TUI monitor | `top`, `htop` |
| **`hyperfine`** | CLI benchmarking | Statistical command-line timing | `time` |
| **`shellcheck`** | Static analysis | Shell script linter & bug detector | Manual inspection |

---

## 4. Multi-Agent Tool Provisioning Protocol

`ShellMaster` accepts tool provisioning requests delegated by [`Benchmarket`](../Benchmarket/AGENTS.md) or [`Orchestrator`](../Orchestrator/AGENTS.md):

```json
{
  "sender": "Benchmarket",
  "recipient": "ShellMaster",
  "task": "provision_cli_tools",
  "payload": {
    "tools": ["hyperfine", "oha", "wrk"],
    "manager_preference": ["brew", "cargo", "uv", "pixi"],
    "verification_command": "hyperfine --version && oha --version"
  }
}
```

### Execution Strategy:
1. Verify if the tool already exists: `command -v <tool>`.
2. If missing, attempt installation via Homebrew: `brew install <tool>`.
3. If not available in Homebrew, check Cargo: `cargo install <tool>`.
4. If Python-based CLI: `uv tool install <tool>`.
5. Verify exit status `0` and return execution result to caller.
