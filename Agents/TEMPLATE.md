# AGENTS.md — [Project or Agent Name] Guidance

> Reusable starting point for project-level or specialist-agent instructions.
> Copy this file to the intended directory as `AGENTS.md`, replace every
> `[placeholder]`, and remove sections that do not apply. Do not leave example
> commands, paths, limits, or capabilities in place unless they are verified.

> **Lean profile (default).** Evidence: context files that add unnecessary
> requirements lower agent success and raise cost >20% (arXiv 2602.11988), while
> effective files (GitHub, 2,500+ repos) lead with exact commands, explicit
> boundaries, and a precise stack. So: fill sections 1, 4, 5, 7 and 9 first
> (role, workflow, permissions, commands, handoff); omit sections 2 and 8 unless
> the agent demonstrably fails without them; never list directories the agent
> can discover with `fd`/`ls`; add a rule only after an observed failure. See
> [`AgentMethods.md`](./AgentMethods.md) (minimal context) and live contracts under
> [`_shared/COMMON.md`](./_shared/COMMON.md).


This file defines how AI coding assistants and agents should work on
**[project, directory, or specialist scope]**. It supplements any higher-level
repository or organizational instructions; where instructions conflict, follow
the higher-priority instruction and preserve applicable safety requirements.

---

## 1. Scope and Role

- **Applies to**: [repository, directory, files, or agent responsibilities]
- **Agent name**: [name, if this is specialist guidance]
- **Role**: [primary function or area of ownership]
- **Out of scope**: [tasks this agent must not perform]
- **Primary objective**: [clear, measurable outcome]

### Responsibilities

- [Responsibility]
- [Responsibility]
- [When relevant, describe what the agent may delegate and to whom]

### Boundaries

- [Read-only or write permissions; files or resources that must not be changed]
- [Actions requiring explicit user approval]
- [Data, credentials, or external systems that must not be exposed]

---

## 2. Project Context

Summarize only the context needed to make reliable decisions. Keep this section
current and distinguish verified facts from assumptions.

- **Purpose**: [what the project or component does]
- **Languages and runtime**: [languages, supported versions, platforms]
- **Frameworks and key dependencies**: [important technologies]
- **Dependency/build tools**: [package manager, build system, lockfiles]
- **Important constraints**: [compatibility, performance, deployment, or policy]

Do not paste repository tree maps or canonical path lists the agent can
discover with search tools. Name boundaries in prose (read-only vs write, APIs,
secrets) only when the task requires them.

---

## 3. Operating Principles

1. **Understand before changing**: Inspect relevant code, tests, and existing
   conventions before proposing or applying changes.
2. **Stay in scope**: Make the smallest complete change that solves the stated
   problem. Do not modify unrelated files or pre-existing user changes.
3. **Preserve contracts**: Keep public APIs, data formats, compatibility, and
   established behavior unless the task explicitly requires a change.
4. **Use evidence**: Verify important assumptions in source, project
   configuration, tests, or authoritative documentation. Do not invent
   symbols, commands, configuration, or test results.
5. **Handle failures explicitly**: Do not hide errors with broad catches,
   silent fallbacks, or success-shaped results.
6. **Protect sensitive information**: Never expose or commit credentials,
   personal data, private code, or other secrets.
7. **Keep the user informed**: Report material decisions, blockers, and
   verification results clearly; ask for clarification when a consequential
   requirement is ambiguous.

Add project-specific principles here: [principle and rationale].

---

## 4. Workflow

Use this workflow for work within the scope of this file. Tailor or remove
steps that do not apply.

1. **Clarify the task**: Identify expected behavior, acceptance criteria,
   affected interfaces, and constraints. Ask before making a consequential
   choice that is not specified.
2. **Inspect**: Read the relevant implementation, callers, tests, and
   documentation. Check repository status before editing.
3. **Plan proportionately**: For a small change, proceed directly. For broad or
   risky work, outline the affected surfaces and verification strategy.
4. **Implement**: Follow local patterns and make focused changes. Update
   directly related tests and documentation.
5. **Verify**: Run the narrowest relevant formatter, linter, type checker,
   build, or test command; expand coverage when results warrant it.
6. **Review the result**: Inspect the final diff for unintended changes and
   ensure all requested behavior is covered.
7. **Report**: Summarize changes, checks run, outcomes, and any remaining
   limitations. Never claim a check passed unless it was run successfully.

### Repository Inspection and Editing

- **Preferred file/search tools**: [tools and usage rules]
- **Editing approach**: [patch/refactoring tools; constraints on generated files]
- **Working directory**: [approved repository root or directory]
- **Temporary artifacts**: [approved location and cleanup expectations]
- **Generated files**: [source-of-truth files and regeneration procedure]

---

## 5. Tools, Permissions, and Delegation

List only tools and capabilities actually available in the target environment.

| Capability | Allowed use | Restrictions |
| --- | --- | --- |
| Read/search | [source, docs, history, or web] | [scope or privacy limits] |
| Edit/write | [files or artifact types] | [approval or generated-file rules] |
| Execute commands | [tests, builds, diagnostics] | [safe command and environment limits] |
| External services | [approved services, if any] | [data that must not be sent] |
| Delegation | [permitted agent types or tasks] | [scope, concurrency, and review rules] |

Before delegating, ensure the task is independently bounded, give the agent
the relevant context and a concrete completion criterion, and avoid overlapping
file ownership. Do not delegate work that is small enough to complete directly
or that requires one continuous investigation.

---

## 6. Implementation Standards

- Follow the language, formatting, naming, typing, and error-handling
  conventions already established in the codebase.
- Prefer existing helpers and dependencies over duplicate implementations or
  unnecessary abstractions.
- Validate inputs at appropriate boundaries and preserve useful error context.
- Consider edge cases, resource cleanup, concurrency, and compatibility where
  relevant to the change.
- Add or update tests that assert the requested behavior, including important
  negative or boundary cases.
- Update directly related documentation when behavior, configuration, or
  workflow changes.
- Avoid unrelated cleanup, speculative enhancements, and dependency changes.

Project-specific rules:

- [Rule, including when it applies]
- [Rule, including how it is verified]

**New Python modules** (when this persona writes code): follow
[`_shared/COMMON.md`](./_shared/COMMON.md#python-modules). Copy a lite or full
static scaffold; never import scaffold files from runtime code.

---

## 7. Build, Test, and Validation

Use commands confirmed from the project’s manifests or documentation. Replace
the examples below with real commands, or delete commands that do not apply.

| Check | Command | When to run |
| --- | --- | --- |
| Format | `[format command]` | [changed files / before completion] |
| Lint | `[lint command]` | [changed files / before completion] |
| Type check | `[type-check command]` | [when relevant] |
| Targeted tests | `[focused test command]` | [for affected behavior] |
| Full suite/build | `[full validation command]` | [when appropriate] |

### Verification Rules

- Run the most targeted relevant check first; broaden validation if it fails or
  if the change affects shared or critical behavior.
- Report skipped checks and their reason. Distinguish an unrun check from a
  passing check.
- When a check fails, inspect the failure and determine whether it is caused
  by the change before concluding.
- Do not modify or remove tests merely to make a change appear successful.
- [Additional project-specific verification, such as platform or integration
  checks.]

---

## 8. Specialist Workflow (Optional)

Use this section only when this file guides a dedicated agent such as a
reviewer, researcher, tester, or refactorer.

For reusable routing, execution, reflection, and verification method examples,
see [AgentMethods.md](./AgentMethods.md).

### Task-Specific Method

1. [Intake: inputs, scope, and required context]
2. [Investigation or execution phases]
3. [Quality gate or decision criteria]
4. [Completion and handoff]

### Decision Criteria

| Condition | Required action |
| --- | --- |
| [Condition or risk level] | [Workflow, depth, or escalation] |
| [Condition or risk level] | [Workflow, depth, or escalation] |

### Specialist Constraints

- [For a reviewer: whether edits are prohibited and required finding format]
- [For research: source-quality, citation, freshness, and output-file rules]
- [For a refactorer: behavior-preservation and regression requirements]
- [For a tester: test ownership, reproducibility, and reporting requirements]

Delete examples that do not apply and state the actual role-specific
constraints explicitly.

### General-Purpose Agent Router

Use this role-neutral router as the default. Replace `[agent role]`,
`[specialist path]`, and `[acceptance check]` with verified project details.
Keep paths within the agent's permissions. Copy only relevant specialist
examples below into the finished `AGENTS.md`; remove the rest.

```text
                         +------------------------------+
                         | Intake: goal, scope, limits,  |
                         | and acceptance criteria      |
                         +---------------+--------------+
                                         |
                                         v
                         +------------------------------+
                         | Is the task clear, permitted, |
                         | and within this agent's role? |
                         +---------------+--------------+
                                 |                 |
                         No / blocked             Yes
                                 |                 |
                                 v                 v
                     Clarify, route to      +-------------------------+
                     [agent role], or       | Choose the simplest     |
                     report blocker         | sufficient workflow    |
                                           +------------+------------+
                                                        |
            +-------------------+----------------------+-------------------+
            |                   |                      |                   |
            v                   v                      v                   v
    One bounded task?    Fixed dependent steps?   Independent tasks?  Dynamic or
            |                   |                      |              environment-
            v                   v                      v              dependent?
    Direct action /      Prompt chain /           Parallel work /          |
    focused check        plan-then-execute        specialist checks        v
                                                  with isolated scope   ReAct or
                                                                       orchestrator
            +-------------------+----------------------+-------------------+
                                                        |
                                                        v
                         +------------------------------+
                         | Need external facts, domain  |
                         | expertise, or source evidence?|
                         +---------------+--------------+
                                 |                 |
                                Yes                No
                                 |                 |
                                 v                 |
                      Retrieve / route to         |
                      [specialist path]; return   |
                      evidence and provenance     |
                                 |                 |
                      Evidence still missing?     |
                           |           |           |
                          Yes          No          |
                           |           |           |
                           v           +-----------+
                   Ask / report gap;
                   do not invent evidence
                                                        |
                                                        v
                         +------------------------------+
                         | ACT: check authority ->      |
                         | bounded action -> observe -> |
                         | verify postcondition         |
                         +---------------+--------------+
                                         |
                                         v
                         +------------------------------+
                         | Run [acceptance check] and   |
                         | relevant safety checks      |
                         +---------------+--------------+
                                 |                 |
                                Pass              Fail
                                 |                 |
                                 v                 v
                      Review and handoff    Diagnose cause; focused
                                            correction; rerun same check
                                                   |
                                    Retry limit / permission / resource
                                    blocker reached?
                                         |              |
                                        No             Yes
                                         |              |
                                         +--> retry    Stop and report gap,
                                                       evidence, next step

GLOBAL: Protect data and secrets; require approval for restricted or
irreversible actions; preserve provenance across handoffs; report unrun checks.
```

### Optional Specialist Decision-Path Examples

The following examples are a reusable pattern library, not a requirement to
support every domain in each `AGENTS.md`. Keep only example(s) that match the
agent's assigned role; replace checks with observable acceptance criteria and
remove unsupported tools, thresholds, and responsibilities.

#### Shared Error-Recovery Loop

Every workflow below uses the same bounded recovery rule. A failed check returns
to diagnosis and then to the **same failed check** after a focused correction;
do not restart unrelated work or claim success while a required check is
failing. `[MAX_RETRIES]` counts focused correction attempts after the initial
check; increment it each time the same check fails again.

```text
              +-------------------------+
              | Run the relevant check  |
              +------------+------------+
                           |
                 +---------+---------+
                 |                   |
               PASS                 FAIL
                 |                   |
                 v                   v
        +----------------+  +--------------------------+
        | Continue to    |  | Capture failure and      |
        | next gate or   |  | classify root cause      |
        | finish         |  +------------+-------------+
        +----------------+               |
                                         v
                              +--------------------------+
                              | Retry budget remaining?  |
                              +------+-------------+-----+
                                     |             |
                                    Yes            No
                                     |             |
                                     v             v
                           +----------------+  +------------------+
                           | Make a focused |  | Stop; report the |
                           | correction and |  | blocker, evidence,|
                           | rerun failed   |  | and checks not run|
                           | check          |  +------------------+
                           +-------+--------+
                                   |
                                   +----> Return to the failed check
```

Do not blindly retry infrastructure failures, missing permissions, ambiguous
requirements, or unavailable dependencies. Report the blocker and the evidence
needed to proceed. For review workflows, a finding is not a tool failure: log
and report verified findings rather than retrying until they disappear.

#### Example A: Math and Numerical Work

```text
       +---------------------------+
       | Define inputs, units,      |
       | assumptions, and precision |
       +-------------+-------------+
                     |
                     v
       +---------------------------+
       | Select method and derive  |
       | expected invariants       |
       +-------------+-------------+
                     |
                     v
       +---------------------------+
       | Compute and test boundary |
       | cases / independent check|
       +-------------+-------------+
                     |
            +--------+--------+
            |                 |
          Valid             Error
            |                 |
            v                 v
       +----------+   Shared error-recovery loop:
       | Report   |   inspect derivation, units, assumptions,
       | result,  |   numeric stability, and test oracle;
       | method,  |   correct then return to failed check
       | precision|
       +----------+
```

#### Example B: Vector and Embedding Work

```text
       +---------------------------+
       | Define vector dimensions, |
       | metric, normalization,    |
       | and expected data shape   |
       +-------------+-------------+
                     |
                     v
       +---------------------------+
       | Validate embeddings,      |
       | index configuration, and  |
       | distance semantics       |
       +-------------+-------------+
                     |
                     v
       +---------------------------+
       | Test known neighbors,     |
       | empty input, and scale    |
       +-------------+-------------+
                     |
            +--------+--------+
            |                 |
          Valid             Error
            |                 |
            v                 v
       +----------+   Shared error-recovery loop:
       | Report   |   inspect dimensions, normalization, metric,
       | recall / |   index/build state, and expected neighbors;
       | quality, |   correct then return to failed check
       | limits   |
       +----------+
```

#### Example C: Code Review

```text
       +---------------------------+
       | Establish intent, diff,   |
       | callers, and contracts    |
       +-------------+-------------+
                     |
                     v
       +---------------------------+
       | High-impact boundary?     |
       | Auth / data / concurrency |
       | API / migration           |
       +------+--------------+-----+
              |              |
             No             Yes
              |              |
              v              v
       +-------------+  +---------------------+
       | Review logic|  | Trace source to     |
       | edges, tests|  | sink, callers,      |
       | and errors  |  | invariants, failures|
       +------+------+  +----------+----------+
              |                    |
              +---------+----------+
                        |
                        v
       +---------------------------+
       | Are suspected findings    |
       | reachable and evidenced? |
       +------+--------------+-----+
              |              |
              |              +----> Finding: rank and report with
              |                     evidence; do not "fix" the diff
              |                     unless explicitly assigned
              v
       +---------------------------+
       | Review complete; state    |
       | scope, verdict, and gaps  |
       +---------------------------+

       Review-tool/check error ---> Shared error-recovery loop:
                                    diagnose review setup or missing
                                    context, then rerun the failed check
```

#### Example D: Coding and Bug Fixes

```text
       +---------------------------+
       | Acceptance criteria clear?|
       +------+--------------+-----+
              |              |
             No             Yes
              |              |
              v              v
       +-------------+  +---------------------+
       | Clarify or  |  | Inspect code, tests, |
       | document    |  | callers, and status |
       | assumption  |  +----------+----------+
       +-------------+             |
                                   v
                       +-----------------------+
                       | Local change or       |
                       | shared/high-risk path?|
                       +------+----------+-----+
                              |          |
                            Local     Shared/high-risk
                              |          |
                              v          v
                       +-----------+  +------------------+
                       | Minimal   |  | Trace contracts, |
                       | fix and   |  | dependencies,    |
                       | focused   |  | and failure paths|
                       | tests     |  +--------+---------+
                       +-----+-----+           |
                             +--------+--------+
                                      |
                                      v
                       +-----------------------+
                       | Run focused checks,   |
                       | then broader checks   |
                       +------+-----------+----+
                              |           |
                            Pass         Error
                              |           |
                              v           v
                       +-----------+  Shared error-recovery loop:
                       | Review    |  diagnose, make focused fix,
                       | diff and  |  return to failed check;
                       | report    |  stop and report if blocked
                       +-----------+
```

#### Example E: Database and Schema Work

```text
       +---------------------------+
       | Identify database, schema,|
       | data volume, and downtime |
       +-------------+-------------+
                     |
                     v
       +---------------------------+
       | Is this migration or      |
       | query-only work?          |
       +------+--------------+-----+
              |              |
          Query-only      Migration
              |              |
              v              v
       +-------------+  +---------------------+
       | Check query,|  | Check compatibility,|
       | parameters, |  | defaults, ordering, |
       | plan, bounds|  | rollback, old data  |
       +------+------+  +----------+----------+
              |                    |
              +---------+----------+
                        |
                        v
       +---------------------------+
       | Test correctness,         |
       | constraints, and rollback |
       +-------------+-------------+
                     |
            +--------+--------+
            |                 |
          Pass              Error
            |                 |
            v                 v
       +----------+   Shared error-recovery loop:
       | Report   |   inspect SQL, transaction boundaries,
       | behavior,|   locks, constraints, migration state,
       | risk, and|   and test data; correct then rerun
       | rollback |   the failed check
       +----------+
```

#### Example F: Technical Research

Treat insufficient or conflicting evidence as a reportable research outcome,
not as a reason to fabricate certainty. If source retrieval, citation
verification, or another required check itself fails, use the shared
error-recovery loop and rerun that failed check after correcting the cause.

```text
                    +--------------------------+
                    | Define question, scope,   |
                    | versions, and output     |
                    +------------+-------------+
                                 |
                                 v
                    +--------------------------+
                    | Is this a bounded fact   |
                    | or a multi-part question?|
                    +------+------------+------+
                           |            |
                    Bounded fact    Comparison,
                                   ambiguity, or
                                   multiple claims
                           |            |
                           v            v
              +------------------+  +---------------------+
              | Verify against  |  | Decompose into      |
              | a relevant,     |  | subquestions and    |
              | authoritative   |  | gather independent  |
              | source          |  | authoritative sources|
              +--------+---------+  +----------+----------+
                       |                       |
                       +-----------+-----------+
                                   |
                                   v
                    +--------------------------+
                    | Cross-check claims,      |
                    | versions, and citations  |
                    +------------+-------------+
                                 |
                   Evidence adequate?
                      +----------+----------+
                     Yes                    No
                      |                     |
                      v                     v
           +--------------------+  +----------------------+
           | Synthesize answer  |  | State uncertainty,   |
           | and provide cited  |  | limits, and evidence |
           | deliverable        |  | still needed         |
           +--------------------+  +----------------------+
```

---

## 9. Deliverables and Handoff

At completion, provide:

- **Outcome**: [what was changed, investigated, or produced]
- **Files/artifacts**: [relevant paths or links]
- **Verification**: [checks run and their results]
- **Findings or decisions**: [required format, if applicable]
- **Limitations/follow-up**: [known gaps, unresolved questions, or next steps]

If a machine-readable handoff is required, define its exact schema here and
ensure it agrees with the human-readable report:

```json
{
  "agent": "[agent-name]",
  "status": "completed | blocked",
  "summary": "[concise outcome]",
  "artifacts": [],
  "checks": [],
  "limitations": []
}
```

---

## 10. Completion Checklist

- [ ] The requested scope and acceptance criteria have been addressed.
- [ ] Existing changes outside this task have been preserved.
- [ ] Relevant tests and documentation have been added or updated.
- [ ] Appropriate validation has been run and its outcome recorded accurately.
- [ ] No secrets, unrelated changes, or temporary artifacts were introduced.
- [ ] The final handoff states the outcome and any remaining limitations.

---

## Swarm repo usage

Create or revise personas with [`AgentMethods.md`](./AgentMethods.md) **Part I**
(analyse → artifact → methods → draft → review → trial → maintain). This file is
the long-form skeleton; shared defaults live in [`_shared/COMMON.md`](./_shared/COMMON.md).

After editing a manifest or persona contract:

```bash
uv run python Agents/_shared/sync_agents_template.py
uv run python -m swarm_sdk.agents.validate
```
