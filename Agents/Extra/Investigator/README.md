# Investigator: Reverse-Engineering Field Guide

> Practical companion to [`agents.md`](./agents.md). Research checked 2026-10-15. Use only for authorized analysis; begin read-only and preserve the original evidence.

## Purpose and limits

Reverse engineering turns observable artifacts into a tested explanation of program behavior. It can recover likely structure and algorithms from source or compiled code, but automated parsers, disassemblers, decompilers, signatures, and runtime traces each have coverage limits. Treat every result as evidence with scope, not as a verdict. A suspicious feature or failed signature check alone does not prove compromise.

The D.A.R.S. labels below are this agent’s workflow mnemonic. NIST SP 800-86 describes a distinct forensic process—collection, examination, analysis, and reporting—and recommends preserving integrity and documenting methods. Use both: D.A.R.S. controls the investigation loop; the NIST phases inform evidence handling. [NIST SP 800-86](https://csrc.nist.gov/pubs/sp/800/86/final)

## Ordered workflow

### 1. Define the question and boundary

- State the question as a claim that can be supported or weakened by evidence.
- List authorized paths, artifacts, accounts, time range, system boundary, and prohibited actions.
- Record competing benign and suspicious hypotheses and what observation would distinguish them.
- Decide whether static inspection is enough. Dynamic execution is an exception requiring explicit authorization and a suitable isolated environment.

### 2. Acquire and preserve

- Record original path, file type, size, timestamps with timezone, ownership/permissions, extended attributes, tool versions, and acquisition method.
- Hash originals and working copies with an approved digest and compare the results. A matching hash supports that the copy has not changed since acquisition; it does not prove origin or benignness.
- Preserve originals. Analyze a working copy when transformation or tool annotation is needed. Keep command output and notes with secrets and private data redacted.
- Inventory hidden, ignored, untracked, generated, vendored, embedded, and symlinked material. Resolve a symlink’s target before assuming its contents are in scope.
- Maintain a short evidence ledger. For formal matters, follow the organization’s evidence and chain-of-custody policy; this guide is not legal advice.

### 3. Triage the artifact before interpreting it

- Identify whether the target is source, script, archive, document, bytecode, object file, executable, library, or data. Do not trust an extension alone.
- For binaries, establish container format, architecture, endianness, entry point, sections/segments, imports/exports, symbols, relocations, debug data, resources, and signature state before disassembly.
- Match the parser and disassembler configuration to the actual architecture and format. Consult the format specification for details: [Mach-O loader definitions (Apple XNU)](https://github.com/apple-oss-distributions/xnu/blob/main/EXTERNAL_HEADERS/mach-o/loader.h), [Microsoft PE/COFF format](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format), and [ELF object format](https://refspecs.linuxfoundation.org/LSB_5.0.0/LSB-Core-generic/LSB-Core-generic/elf-generic.html).
- Treat entropy, unusual sections, stripped symbols, imports, strings, and signature results as leads. Validate them against code paths, format metadata, known-good builds, and provenance.

### 4. Inspect source structurally

1. Identify language, runtime/compiler version, build flags, dependencies, generated sources, entry points, and conditional compilation. For compiled projects, use the real build configuration (such as a compilation database) when available.
2. Parse with the language’s native parser or compiler frontend. Record files skipped, syntax errors, grammar version, and configuration. A successful AST parse does not prove that the program compiles or that dynamic behavior is represented. Python’s AST grammar may change by release; node source locations and extraction helpers are documented in the [Python AST reference](https://docs.python.org/3/library/ast.html).
3. Build a symbol/import map and trace declarations to callers. Follow callbacks, async tasks, event handlers, plugin registration, reflection, dynamic imports, FFI, generated dispatch tables, and indirect calls; plain text search misses some of these relationships.
4. Draw control-flow and state-transition sketches for relevant functions. Inspect error/exception paths, early returns, `finally`/cleanup behavior, feature flags, environment-dependent branches, loops, recursion, concurrency, and code reached only through configuration.
5. Trace data from sources through transformations to sensitive sinks: process launch, filesystem writes/deletes, network clients, credential stores, persistence/autostart, dynamic evaluation/loading, and permission changes. Follow values across helper functions and serialization boundaries.
6. Inspect code that can be easy to overlook: dotfiles, ignored files, build/install hooks, templates, macros, preprocessor branches, generated/vendor code, dead-looking branches, Unicode format controls (including bidirectional or zero-width characters), and non-printable bytes. Display suspicious Unicode as escaped code points; do not normalize the evidence before analysis. [MITRE ATT&CK T1027](https://attack.mitre.org/techniques/T1027/) catalogs concealment methods including packing, dynamic API resolution, embedded payloads, and invisible Unicode. These are investigation leads, not proof of malicious intent.

For Python, `ast.parse`, `ast.walk`, node location fields, and `ast.get_source_segment` can support structural searches. `ast.walk` traversal order is unspecified; do not infer execution order from its output. For C and C++, compiler flags and preprocessor definitions affect the translation unit being parsed. Always record the parser and configuration used.

### 5. Inspect compiled code and validate tool assumptions

- Start with entry points and references; follow control-flow edges and calls. Compare disassembly, decompiler output, byte view, symbols, and format metadata instead of trusting one view.
- Use a layered analysis: basic format/function/reference analysis first, then selected deeper analyzers on the functions or regions that answer the question. Ghidra’s official training covers entry-point analysis, cross-references, function graphs/call trees, decompilation, and this layered approach. [Ghidra beginner guide](https://ghidra.re/ghidra_docs/GhidraClass/Beginner/Introduction_to_Ghidra_Student_Guide.html)
- Decompilation is a reconstruction. It infers high-level expressions, types, prototypes, and control flow from machine instructions; the result is not recovered original source. Validate function boundaries, calling conventions, argument/return types, tail calls/shared returns, no-return functions, jump tables, indirect branches, and code/data boundaries. Ghidra documents cases where incorrect signatures or control-flow assumptions distort output. [Ghidra: Improving Disassembly and Decompilation](https://ghidra.re/ghidra_docs/GhidraClass/Advanced/improvingDisassemblyAndDecompilation.pdf) · [Ghidra decompiler design notes](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/Features/Decompiler/src/decompile/cpp/docmain.hh)
- When source and binary are both available, compare compiler output against source and check whether the build configuration, dependency versions, and artifact hashes actually match. Similar names or version strings alone do not establish a match.

### 6. Reconstruct the algorithm

Write an explicit, falsifiable model before naming an algorithm:

| Element | Questions |
| --- | --- |
| Inputs | Which arguments, files, environment values, messages, or global state affect the result? What validation or coercion occurs? |
| State | What data structures, caches, counters, locks, and persistent values change? Which transitions are possible? |
| Transformations | What operations, encodings, hashes, comparisons, sorting, filtering, or arithmetic occur, and in what order? |
| Branches | Which predicates select each path? What are boundary values, defaults, retries, and failure paths? |
| Outputs and effects | What is returned, emitted, written, transmitted, or left behind? What is observable only after another component acts? |
| Invariants | Which properties must remain true across iterations or state transitions? Which are assumptions rather than demonstrated facts? |

- Recover a small pseudocode model from AST/control flow or disassembly. Map branches, loop bounds, state transitions, and error cases before inferring intent.
- Compare the model with tests, fixtures, public specifications, known vectors, or traces. Use synthetic boundary inputs and differential checks on authorized copies; include negative and malformed inputs where safe.
- Report complexity only when the input model and relevant paths are understood. State assumptions and worst-case branches; avoid a precise bound when dynamic dispatch or external services dominate behavior.
- For optimized or obfuscated binaries, reason from instructions and data dependencies. Decompiled variable names and pretty output are hints, not evidence of original identifiers or intent.

### 7. Corroborate static findings with controlled observations

- Begin with static analysis. Run code only when needed to answer a material question, explicitly authorized, and inside an isolated disposable environment with synthetic data, a recorded baseline, and restricted network access.
- Observe the exact test inputs and environment. Capture only relevant process, file, registry/configuration, memory, and network effects; avoid attaching real credentials or personal accounts.
- Compare observed paths with the static model. A runtime trace demonstrates behavior for the executed inputs and conditions; it does not establish behavior on unexecuted paths.
- If behavior contradicts the model, return to **Acquire** for exact versions/configuration or **Reverse-engineer** for the specific branch, dependency, or call boundary. Do not force the evidence to fit the initial hypothesis.
- Never execute unknown code on the analyst’s host, disable security controls, or connect a sample to a production network.

## Tool selection

Verify that a tool is installed and check its own help/version before use. Select tools by artifact, not by habit.

| Need | Tool families / examples |
| --- | --- |
| Inventory and search | `fd`, `rg` (include hidden/ignored paths deliberately), `file`, `shasum`, `jq`, `plutil`, `sqlite3` |
| macOS executable | `codesign`, `spctl`, `xattr`, `otool`, `nm`, `strings`, `lldb` (read-only/static first; do not infer trust from a single result) |
| AST / source structure | Language-native parser/compiler front end; Python `ast`; Clang AST tooling for C/C++ when configured with the target build flags |
| Binary analysis | Ghidra, LLDB, format-specific parsers, disassembler/decompiler already approved and installed |
| Runtime observation | Debugger, syscall/process/file/network tracing tools in a disposable isolated lab; record exact versions and configuration |

Do not install tools globally or download and run an analyzer without authorization. Do not pipe network content into a shell. Never upload private source, logs, binaries, hashes not already public, credentials, or personal data to a web service.

## Evidence and reporting standard

For each important conclusion, record:

| Field | Record |
| --- | --- |
| Claim | One narrow, testable statement |
| Evidence | Exact path, line/address, hash, timestamp, or log locator |
| Method | Command/tool/version/configuration and relevant output (redacted) |
| Class | Direct observation, inference, or unresolved hypothesis |
| Confidence | High/medium/low with the reason; do not use a numeric score without a defined scale |
| Alternatives | Benign explanations and evidence that would distinguish them |
| Limits | Unparsed files, untested branches, unavailable baselines, failed commands, or missing telemetry |

Report findings by severity and confidence, state what was not established, and provide reproducible commands and safe next steps. Do not call software “malware,” “clean,” or “compromised” from one indicator alone.

## Ordered completion checklist

1. Define scope, authorization, hypotheses, and prohibited actions.
2. Record baseline, provenance, metadata, versions, and hashes; preserve originals.
3. Inventory hidden, ignored, generated, linked, embedded, and Unicode-bearing content.
4. Identify source languages/build configuration or binary formats/architectures.
5. Parse source and report coverage; map entry points, calls, control flow, and data flow.
6. Trace input-to-effect paths and inspect hard-to-see branches and dynamic boundaries.
7. Reconstruct algorithm/state behavior and test hypotheses against safe known inputs or specifications.
8. Validate disassembler/decompiler assumptions; compare with independent evidence.
9. Use controlled runtime analysis only when necessary, authorized, and isolated.
10. Revisit acquisition or analysis when evidence conflicts; log unresolved gaps.
11. Write an evidence-led report with alternatives, confidence, limitations, and safe next steps.
12. Preserve originals and make no remediation or outward-facing change unless separately authorized.

## Primary references

- [NIST SP 800-86 — Guide to Integrating Forensic Techniques into Incident Response](https://csrc.nist.gov/pubs/sp/800/86/final) — collection, examination, analysis, reporting, integrity, and documentation principles.
- [Python `ast` documentation](https://docs.python.org/3/library/ast.html) — AST grammar, traversal, node locations, and source extraction APIs.
- [Ghidra beginner training](https://ghidra.re/ghidra_docs/GhidraClass/Beginner/Introduction_to_Ghidra_Student_Guide.html) and [advanced disassembly/decompilation training](https://ghidra.re/ghidra_docs/GhidraClass/Advanced/improvingDisassemblyAndDecompilation.pdf) — analysis workflow and common recovery pitfalls.
- [Ghidra decompiler design notes](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/Features/Decompiler/src/decompile/cpp/docmain.hh) — recovery stages such as control-flow structuring, type propagation, and function-prototype recovery.
- [Apple XNU Mach-O loader definitions](https://github.com/apple-oss-distributions/xnu/blob/main/EXTERNAL_HEADERS/mach-o/loader.h), [Microsoft PE/COFF format](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format), and [Linux Standard Base ELF format](https://refspecs.linuxfoundation.org/LSB_5.0.0/LSB-Core-generic/LSB-Core-generic/elf-generic.html) — primary executable-format references.
- [MITRE ATT&CK T1027 — Obfuscated Files or Information](https://attack.mitre.org/techniques/T1027/) — taxonomy of concealment techniques to guide coverage checks, not a maliciousness verdict.
