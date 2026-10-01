# Gemini CLI Project Guidelines — LangGraph Swarm SDK

These rules apply to all agent interactions and coding tasks in this repository.

---

## 1. File Creation & Naming Discipline

- **No Arbitrary `.md` Files**:
  - Never invent, generate, or write `.md` files with arbitrary, strange, or unsolicited names.
  - Only create or modify markdown files that the user explicitly ordered, adhering strictly to the exact file path and name requested.
  - Do not create stray summary files, temporary note files, or exploratory markdown dumps in the workspace.

## 2. Core Operating Cycle: Think → Plan → Verify → Act

```text
[ANALYSE & RESEARCH] → [THINK IN MULTI-STEPS] → [ESTABLISH SUCCESS CRITERIA] → [ACT (EFFICIENT TOOLS)] → [VERIFY GATES]
```

1. **Think More**:
   - Deeply analyze the problem, architectural context, and edge cases before making any file modifications.
   - Resist reflexive edits. Form a coherent hypothesis and understand system-wide implications.

2. **Analyse Before Changing**:
   - Inspect existing conventions, callers, tests, and configuration files (`Main/config/swarm.yaml`, `Agents/*/agent.yaml`).
   - Trace data flows and find root causes instead of applying superficial symptom patches.

3. **Think in Multi-Step Tasks**:
   - Decompose complex requirements into structured, dependency-ordered tasks.
   - Clarify prerequisites, shared state, and disjoint file boundaries between sub-tasks.

4. **Check Success Criteria First**:
   - Explicitly define what constitutes success before taking action:
     - Exact test commands to pass (`uv run ... pytest ...`).
     - Required type check and lint passes (`ruff`, `ty`).
     - Observable behavior changes and benchmark targets.
   - Never claim a task is complete until success criteria are verified with fresh execution evidence.

5. **Improve with Web Search When Needed**:
   - When external APIs, library version differences (Python 3.14+, PyOpenCL, LangChain, fastembed), or documentation are uncertain, consult authoritative web sources before guessing.
   - Prefer official documentation, release notes, and primary sources over outdated blogs.

6. **Then Act**:
   - Execute the planned changes with surgical precision. Keep diffs focused, preserving surrounding interfaces and conventions.

## 3. File Organization & Code Quality: "Write Long Files"

- **Cohesive, Full-Featured Modules**:
  - Prefer robust, well-structured, comprehensive files containing complete functions, types, and error handling over tiny fragmented stubs or artificial micro-files.
  - Keep related logic, protocols, and helper functions unified in the module where they belong.
- **Python Static Template Alignment**:
  - Every new module begins with a module docstring followed immediately by `from __future__ import annotations`.
  - Follow role patterns in `.cursor/templates/python_static_template.py` (`TypeRole`, `MathRole`, `VectRole`, `DbRole`, `BatchRole`, `CoworkRole`).
- **No Incomplete Implementations**:
  - Avoid placeholders, dummy `pass` implementations, or deferred `TODO`s unless explicitly requested.

## 4. Tool Usage Efficiency: "Avoid Usage of a Lot of Tool Calls"

- **Batch Actions**:
  - Read multiple relevant sections or files in cohesive calls rather than dozens of disjoint, tiny reads.
  - Combine independent checks and avoid interactive or chatty loops.
- **Maximize Information Gain**:
  - Every tool call must have a concrete purpose and expected gain.
  - Do not repeatedly re-read unchanged files or poll background processes in tight loops.
- **Direct Terminal Discipline**:
  - Formulate clear, consolidated commands.
  - Use `uv run ...` to respect the project virtual environment.

## 5. Repository Verification Gates

Always run the narrowest relevant gate first, followed by the repository quality gate before claiming completion:

```bash
# 1. Targeted tests
uv run --extra dev pytest <target_test_file> -q --tb=short

# 2. Quality gate
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 pytest Agents/benchmark -q
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ruff check src Agents/benchmark Main
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ty check src Agents/benchmark Main
uv run python -m swarm_sdk.agents.validate
```
