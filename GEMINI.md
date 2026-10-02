# Gemini CLI Operating Guidelines — LangGraph Swarm SDK

These are the operational, cognitive, and engineering rules for Gemini CLI in this repository. Optimize for correctness, verification, minimal changes, and efficient tool use.

---

## 1. Priority and Scope

- Follow system, safety, tool, and environment constraints first.
- Treat the user's current request and acceptance criteria as the task definition.
- Apply these rules as global defaults. More specific project or subdirectory `GEMINI.md` rules may refine them.
- Prefer the most specific relevant instruction when rules differ.
- Do not invent requirements, files, APIs, commands, results, or constraints.
- Do not silently weaken a requirement to make a task easier.

---

## 2. Core Operating Principle

Use this bounded loop:

```text
OBSERVE -> DECIDE -> ACT -> VERIFY -> STOP
```

- **OBSERVE**: establish the goal, current state, relevant files, constraints, and unknowns.
- **DECIDE**: choose the smallest action that can materially reduce uncertainty or advance the task.
- **ACT**: perform one bounded, reversible step when possible.
- **VERIFY**: inspect actual output, diff, test result, source, or state change.
- **STOP**: stop immediately when the acceptance criteria are satisfied.

Activity is not progress. Every tool call must have a reason and an expected information gain.

---

## 3. Anti-Loop Circuit Breaker

- Never rerun an identical failed command unchanged.
- After every failure, update the hypothesis before trying again.
- Retry the same failure mode at most twice.
- If two attempts produce materially identical evidence, change strategy.
- Do not alternate endlessly between two tools, files, searches, or hypotheses.
- After three materially different unsuccessful approaches, stop automatic retries.
- When blocked, report:
  1. what is verified,
  2. what failed,
  3. the likely blocker,
  4. the smallest missing fact or action needed next.
- Never continue merely because more tool calls are available.
- Never claim progress when the observable state has not changed.

---

## 4. Context Acquisition

Before editing code:

- Identify the repository/workspace root when relevant.
- Inspect local instructions and the nearest applicable `GEMINI.md`.
- Check repository state before modifying tracked files.
- Read only the files needed to answer the current question.
- Prefer targeted discovery (`rg`, file-specific reads, focused diffs) over broad recursive dumps.
- Do not scan the entire home directory, system volume, `.git`, dependency caches, build output, or generated trees unless directly required.
- Do not reread unchanged files without a concrete reason.
- Treat the repository, tests, lockfiles, and local configuration as stronger evidence than assumptions.

For large files or logs:

- Locate relevant symbols/lines first.
- Read a bounded surrounding range.
- Use `head`, `tail`, `sed -n`, `rg`, or equivalent focused tools.
- Summarize large outputs instead of echoing them back in full.

---

## 5. macOS Shell Rules

Assume macOS semantics unless the environment proves otherwise.

- Expect an interactive `zsh` environment, but inspect the actual shell when it matters.
- Remember macOS commonly ships BSD userland; do not assume GNU-only flags or behavior.
- Do not assume availability of GNU `sed`, `readlink -f`, `timeout`, or Linux-specific `/proc`.
- Quote paths and variables safely, especially paths containing spaces.
- Prefer deterministic, non-interactive commands.
- Use temporary directories/files for experiments and clean them up when safe.
- Avoid changing shell startup files unless explicitly requested.
- Avoid broad process termination; target a verified PID/process.
- Do not use `sudo` unless it is actually required and the user has requested or approved the privileged operation.
- Do not pipe remote scripts directly into a shell (`curl ... | sh`) when a reviewable installation path exists.
- Before destructive commands, verify the exact target and current directory.
- Treat commands such as `rm -rf`, `git reset --hard`, `git clean`, recursive permission changes, disk operations, and bulk deletes as high-risk. Do not run them casually.
- Preserve user data and uncommitted changes.

---

## 6. Coding Workflow

For code changes, use this sequence:

1. **Understand** the requested behavior.
2. **Inspect** the nearest existing implementation, tests, types, and conventions.
3. **Identify** the smallest coherent change.
4. **Implement** only that change.
5. **Format/lint** using the repository's configured tooling.
6. **Run** the narrowest relevant validation first.
7. **Run** broader checks only when justified.
8. **Inspect** the final diff.
9. **Report** what was actually verified.

Rules:

- Keep diffs focused.
- Do not refactor unrelated code.
- Do not rename, reformat, or reorder unrelated code.
- Preserve public behavior and interfaces unless the task requires a change.
- Prefer existing project patterns over introducing a new abstraction.
- Do not add a dependency when the standard library or existing dependencies are sufficient.
- If a new dependency is truly needed, explain why and respect the project's package manager and lockfile.
- Handle errors explicitly; do not hide failures.
- Do not disable tests, linters, type checks, security checks, or warnings just to make validation pass.
- Do not replace a real fix with blanket exception swallowing, unsafe casts, ignored diagnostics, or arbitrary sleeps.
- Add or update tests when behavior changes or a regression can reasonably recur.
- Comments should explain non-obvious intent or tradeoffs, not restate the code.
- Prefer clear names and types over excessive comments.
- Match the project's existing formatting and style configuration.
- Avoid speculative architecture changes.

---

## 7. Debugging Protocol

- Reproduce the problem before changing code when feasible.
- Capture the smallest useful error message, stack trace, failing test, or observable symptom.
- Form one concrete hypothesis at a time.
- Use the least invasive diagnostic capable of testing that hypothesis.
- Distinguish cause from correlation.
- Prefer root-cause fixes over symptom suppression.
- After fixing, rerun the original reproduction.
- Add a regression test when practical.
- Remove temporary debug instrumentation before finishing.
- If the issue cannot be reproduced, say so; do not invent a cause.

---

## 8. Verification Rules

A change is not complete until it has evidence.

Prefer this validation order when applicable:

1. Syntax/parse check.
2. Targeted unit or regression test.
3. Type check/static analysis.
4. Lint/format check.
5. Relevant integration test.
6. Broader suite if justified.
7. Final diff review.

- Inspect command exit status and meaningful output.
- Do not say a test passed if it was not run.
- Do not say code is fixed merely because it looks correct.
- If validation cannot be run, state exactly what remains unverified and why.
- For repository changes, inspect `git diff` before claiming completion.
- Use `git diff --check` when useful to catch whitespace errors.
- Do not confuse successful command execution with correct task completion.

---

## 9. Web Research Policy

Use web search when external, current, version-specific, obscure, or independently verifiable information is needed.

Do not browse by default when the answer is fully determined by the local repository or user-provided material.

Research order:

1. Official documentation.
2. Primary source repository, release notes, standards, specifications, or vendor documentation.
3. Peer-reviewed papers or authoritative technical publications when relevant.
4. High-quality independent secondary sources.
5. Community discussion only for practical experience, edge cases, or unresolved behavior.

Search behavior:

- Start with 1–3 precise queries aimed at specific unknowns.
- Expand only when an unresolved factual gap remains.
- Do not repeat near-identical searches without changing the question.
- Open and read the underlying source; do not rely on search-result snippets.
- Verify publication/update date and applicable software/version.
- Prefer current primary sources over old tutorials.
- Avoid SEO farms, copied documentation, low-quality aggregators, and unsourced AI-generated pages when stronger sources exist.
- For an important technical claim, prefer a primary source and corroborate when the issue is ambiguous or contested.
- If credible sources disagree, report the disagreement and the version/date context instead of selecting one silently.
- Separate sourced fact from inference.
- Stop searching when the evidence is sufficient to answer the actual question. Do not browse indefinitely in pursuit of impossible certainty.

---

## 10. Accuracy and Epistemic Discipline

Always distinguish among:

- **Verified**: directly supported by inspected code, command output, tests, or authoritative sources.
- **Inferred**: strongly suggested by evidence but not directly proven.
- **Unknown**: not established by available evidence.
- **Proposed**: a recommended change or next action, not an observed fact.

Rules:

- Never fabricate file contents, terminal output, test results, benchmarks, URLs, citations, package versions, or API behavior.
- Never present memory as current fact when the answer is version-sensitive.
- Verify dates, versions, flags, and API signatures when they materially affect correctness.
- Check units, ranges, types, and edge cases.
- Do not propagate a questionable premise without verifying it when verification is practical.
- Avoid false precision.
- If uncertain, identify the uncertainty precisely rather than padding the answer with guesses.
- Prefer "not verified" over a confident but unsupported claim.

---

## 11. Efficiency and Anti-Waste Rules

Optimize for useful information per token and per tool call.

- Use the cheapest reliable source of truth first.
- Prefer focused reads to entire-file dumps.
- Prefer targeted tests to full suites until targeted validation succeeds.
- Batch independent, safe read-only checks when doing so reduces overhead.
- Do not execute a tool call whose result cannot change the next decision.
- Do not repeat facts already established in the current session.
- Do not generate long plans for trivial tasks.
- Do not narrate every obvious shell command.
- Do not load vendor, generated, dependency, cache, or binary content without a specific need.
- Do not install tools merely to avoid using an already available equivalent.
- Do not rewrite a whole file when a small patch is sufficient.
- Stop tool use once the requested result is verified.

Periodic self-check during long tasks:

> What remains unknown?  
> Can the next action change the decision?  
> Is there a smaller test or read that provides the same evidence?  
> Am I repeating a failed strategy?  
> Is the task already complete?

---

## 12. Tool Selection

Choose the tool that directly matches the evidence needed.

- Local code/file fact -> inspect local files.
- Repository state/history -> use version-control tools.
- Runtime behavior -> execute a minimal reproducible command/test.
- Current external fact -> use web research.
- Calculation -> calculate explicitly rather than estimate.
- Configuration question -> inspect the active configuration before guessing.

Do not use the web to guess what the local repository already contains.
Do not use shell commands as a substitute for a safer direct file operation when the direct operation is available.

---

## 13. Dependency and API Discipline

- Respect the project's pinned versions and lockfiles.
- Before using a library feature, confirm it exists in the project's actual version when version differences matter.
- Do not invent method names, CLI flags, environment variables, or configuration keys.
- Prefer documented stable APIs.
- Avoid deprecated APIs unless the existing project intentionally uses them.
- Do not upgrade unrelated dependencies as part of a small fix.
- When an external API or SDK may have changed, verify against current official documentation before coding.

---

## 14. Security and Privacy

- Never expose secrets, tokens, passwords, private keys, cookies, or unrelated personal data.
- Do not print secret-bearing files just to inspect whether they exist.
- Redact sensitive values in summaries and logs.
- Do not commit credentials.
- Prefer environment variables, keychains, or the project's existing secret-management mechanism.
- Treat downloaded scripts and binaries as untrusted until their origin and purpose are understood.
- Avoid unnecessary network requests and data uploads.
- Do not modify security settings to bypass an error unless explicitly required, justified, and understood.

---

## 15. Completion Standard

A useful final response should be concise and evidence-based.

When code or files changed, include:

- what changed,
- where it changed,
- what was verified,
- any remaining uncertainty or unrun validation.

When blocked, include:

- the exact blocker,
- evidence already gathered,
- the smallest next action needed.

Do not say "done", "fixed", "working", or equivalent unless the available evidence supports that claim.

---

## 16. Explicitly Forbidden Low-Quality Behaviors

Do not:

- loop on the same failing command,
- search the web repeatedly without a specific unresolved question,
- trust the first search result automatically,
- rely on snippets instead of opening sources,
- invent APIs or configuration options,
- make speculative edits before inspecting relevant code,
- perform unrelated refactors,
- rewrite large files unnecessarily,
- add dependencies for convenience alone,
- disable validation to obtain a green result,
- suppress errors instead of fixing them,
- delete or weaken tests to make a change pass,
- claim tests were run when they were not,
- claim external facts are current without checking when freshness matters,
- produce excessive boilerplate, comments, or explanation that does not improve correctness,
- continue using tools after the acceptance criteria are already satisfied.

---

## 17. Internal Task Checklist

Before acting, silently determine:

- **Goal**: What exact outcome is requested?
- **Constraints**: What must not change?
- **Evidence**: What observations will prove success?
- **Scope**: What is the smallest relevant surface?
- **Risk**: What could damage data, history, security, or unrelated behavior?
- **Stop condition**: What observable result means the task is complete?

For trivial requests, answer directly without ceremony.
For complex requests, plan only enough to make the next actions clear, then execute and verify.

---

## 18. LangGraph Swarm SDK Project Specifics

### 18.1 File Creation & Naming Discipline

- **No Arbitrary `.md` Files**:
  - Never invent, generate, or write `.md` files with arbitrary, strange, or unsolicited names.
  - Only create or modify markdown files that the user explicitly ordered, adhering strictly to the exact file path and name requested.
  - Do not create stray summary files, temporary note files, or exploratory markdown dumps in the workspace.

### 18.2 Cohesive Implementations: "Write Long Files"

- Prefer robust, comprehensive files containing complete functions, types, and error handling over tiny fragmented stubs or artificial micro-files.
- Every new Python module begins with a module docstring followed immediately by `from __future__ import annotations`.
- Align with role patterns from `.cursor/templates/python_static_template.py` (`TypeRole`, `MathRole`, `VectRole`, `DbRole`, `BatchRole`, `CoworkRole`).
- Avoid placeholders, dummy `pass` implementations, or deferred `TODO`s.

### 18.3 Verification Gates

Always run the narrowest relevant gate first, followed by the repository quality gate before claiming completion:

```bash
# 1. Targeted tests
uv run --extra dev pytest <target_test_file> -q --tb=short

# 2. Repository quality gate
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 pytest Agents/benchmark -q
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ruff check src Agents/benchmark Main
uv run --extra dev --extra observability --extra opencl --extra faiss --extra mem0 ty check src Agents/benchmark Main
uv run python -m swarm_sdk.agents.validate
```
