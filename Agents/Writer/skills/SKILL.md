# Writer Skill: Copywriting & Humanizer Engine

> **Scope**: Advanced algorithms, prompt patterns, and structural transformations for humanizing AI text and verifying persuasive copywriting.

---

## 1. Humanizer Rewriting Protocol

### 1.1 Burstiness Injection Pattern
Human writing exhibits high variance in sentence length. Transform uniform AI paragraphs using the **3-1-2 Rhythm Rule**:
- 3 Medium sentences (12-18 words)
- 1 Short punchy sentence (< 6 words)
- 2 Long descriptive compound sentences (22-30 words)

### 1.2 Perplexity Elevation Techniques
1. **Unconventional Openers**: Start sentences with prepositional phrases, conjunctions, or action verbs rather than standard subject-verb structures.
2. **Idiomatic Injection**: Insert contextual colloquialisms, industry-specific shorthand, or natural rhetorical questions.
3. **Anecdotal Context**: Ground abstract claims with concrete, specific real-world examples.

---

## 2. Anti-AI Detection Ruleset

| AI Attribute | AI Characteristic | Humanization Remedy |
| :--- | :--- | :--- |
| **Cadence** | Constant sentence length (~16-20 words) | Alternate between 3-word statements and 35-word complex observations. |
| **Transitions** | "Furthermore", "Moreover", "In summary" | Use natural links: "Also", "Here is why", "That said", or omit entirely. |
| **Vocabulary** | Safe, high-frequency adjectives ("pivotal") | Use vivid, specific verbs and direct language. |
| **Structure** | Standard introduction-body-conclusion | Use hook-first opening, asymmetrical section lengths, and immediate CTAs. |

---

## 3. Copywriting Frameworks

### PAS (Problem - Agitate - Solve)
1. **Problem**: State the reader's pain point directly without fluff.
2. **Agitate**: Detail the hidden cost or frustration of ignoring the problem.
3. **Solve**: Present the solution cleanly with zero buzzwords.

### AIDA (Attention - Interest - Desire - Action)
1. **Attention**: Counter-intuitive headline or bold statement.
2. **Interest**: Surprising data point or storytelling hook.
3. **Desire**: Tangible benefits and emotional payoff.
4. **Action**: Single clear call to action.

---

## 4. Technical Writing & Semantic Verification Protocol

### 4.1 Strict Semantic Verification Checklist
1. **Structural Conformance**: Markdown strictly implements Title -> Alert Metadata -> Summary -> Index -> ASCII Workflow -> Technical Deep Dive -> Trade-off Matrix -> Quantitative Benchmarks ($\Delta\%$) -> Shell Recipes -> Evidence Ledger.
2. **Grounding & Precision**: All constants, kernel `.config` flags, and hardware components must be explicit (e.g. `Intel Xeon E5-2680 v4`, `C612 Wellsburg PCH`, `GK208B Kepler`, `CONFIG_DRM_SIMPLEDRM=y`).
3. **Mathematical Rigor**: All mathematical equations for schedulers and metrics must be rendered using standard LaTeX math blocks ($\mathcal{B} = \sum t_{\text{burst}} / (N_{\text{sleep}} + 1)$).
4. **Zero-Fluff Enforcement**: No marketing adjectives or speculative filler. Concrete commands must have explicit line limits and verified return codes.

### 4.2 Systems & Compilation Specification Recipe (Xeon99 Template)
When generating or auditing compilation plans:
- **Optimization Stack**:
  1. `sccache` + ZSTD L3 compilation caching (`SCCACHE_DIRECT=true`, 50GB storage limit).
  2. Btrfs `compress=zstd:3` (prevents RAM exhaustion vs default ZFS ARC on 16GB nodes).
  3. Dynamic preemption (`CONFIG_PREEMPT_DYNAMIC=y`) with boot parameter `preempt=full`.
  4. BORE scheduler (`CONFIG_SCHED_BORE=y`) burstiness-aware interactive prioritization.
  5. Memory allocator co-design: `mimalloc v3.5+` runtime heap + Google `MiniMalloc` static tensor packing.
- **Kernel Flag & Module Verification**:
  - `CONFIG_MCORE2=y`, `CONFIG_NUMA=y`, `CONFIG_NODES_SHIFT=2`.
  - `CONFIG_DRM_SIMPLEDRM=y`, `CONFIG_SYSFB_SIMPLEFB=y`, `CONFIG_DRM_NOUVEAU=n`.
  - `CONFIG_USB_XHCI_HCD=y`, `CONFIG_USB_XHCI_PCI=y`.
  - `CONFIG_R8169=m`, `CONFIG_IGB=m`, `CONFIG_E1000E=m`.

## 5. OpenAI document templates

Use the matching template skill when a user asks for a structured document or
names a template. Each skill is kept in its own same-named folder:

- [`artifact-template-design-report`](artifact-template-design-report/SKILL.md)
- [`artifact-template-experiment-analysis`](artifact-template-experiment-analysis/SKILL.md)
- [`artifact-template-investment-committee-memo`](artifact-template-investment-committee-memo/SKILL.md)
- [`artifact-template-legal-memorandum`](artifact-template-legal-memorandum/SKILL.md)
- [`artifact-template-minimal-letterhead`](artifact-template-minimal-letterhead/SKILL.md)
- [`artifact-template-strategy-memorandum`](artifact-template-strategy-memorandum/SKILL.md)
- [`artifact-template-system-design`](artifact-template-system-design/SKILL.md)

Keep supplied reference files unchanged. Verify technical claims against
source material before placing them in a template.
