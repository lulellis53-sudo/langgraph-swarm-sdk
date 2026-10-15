# Judge Verification Tools Specification (`Tools.md`)

> **Authoritative Specification**: Verification Tooling Engine for `Agents/Judge`.
> **Primary Purpose**: Multi-engine code fidelity, document equality auditing, and primary-source empirical verification.
> **Engines Covered**: **arXiv** (Document Equality & Prior Art), **Context7** (API & Library Code Fidelity), **DeepWiki** (Theoretical & Algorithmic Fidelity), **PyPI** (Python Package & Wheel Verification), **GitHub** (Source Code & Commit Tree Fidelity).
> **Hardware Target**: MacBook Pro 16-inch 2019 (Intel i7-9750H, 16 GB DDR4, AMD Radeon Pro 5300M, macOS Sonoma x86_64).

---

## 1. Executive Summary & Verification Matrix

The **Judge** agent acts as the supreme quality and claim verification authority in the Swarm ecosystem. To eliminate hallucinations, grade inflation, and unverified assumptions, Judge queries five specialized verification engines to validate claims before issuing a scorecard:

| Tool / Engine | Primary Evaluation Purpose | Fidelity Target | Failure Condition / Hard Gate |
| :--- | :--- | :--- | :--- |
| **arXiv (`Arxiv` / `Arxic`)** | **Document Equality & Prior Art**: Verifies if technical papers, research dossiers, or mathematical formulations are duplicated, derivative, or plagiarized. | Text / Equation Similarity, Citation Lineage | Structural duplicate without attribution ($>80\%$ verbatim match) |
| **Context7** | **Library & Framework Code Fidelity**: Validates classes, method signatures, keyword arguments, and type annotations against canonical library docs. | API Signatures, Type Hints, Version Invariants | Hallucinated kwarg, nonexistent method, deprecated call |
| **DeepWiki / Wikipedia** | **Conceptual & Theoretical Fidelity**: Validates algorithmic definitions, mathematical theorems, asymptotic complexities ($O(n)$ bounds), and protocol state machines. | Algorithmic Correctness, Formal Proofs | Flawed theoretical claims, misstated algorithmic bounds |
| **PyPI (`Pipy`)** | **Package & Dependency Fidelity**: Validates package name existence, release versions, dependency trees, and platform wheel availability (macOS `darwin_x86_64`). | Wheel Compatibility, Release Metadata, Dep Trees | Nonexistent package (typosquatting), missing x86_64 wheel |
| **GitHub** | **Source Code & Commit Fidelity**: Validates canonical repository trees, commit SHAs, line-by-line diffs, pull request statuses, and issue discussion contexts. | Live Source Truth, Commit Lineage, PR Reviews | False claim of merged PR, invalid commit SHA, phantom code |

---

## 2. Master Verification Workflow

```
+===================================================================================================+
|               JUDGE AGENT: MULTI-ENGINE FIDELITY & AUDIT WORKFLOW                                 |
+===================================================================================================+

                                   +--------------------------------+
                                   |   EVALUATION TARGET INBOUND    |
                                   |   (Code, Dossier, Benchmark)   |
                                   +--------------------------------+
                                                   |
                                                   v
                         =====================================================
                         ||            TARGET TRIAGE ROUTER                 ||
                         ||                                                 ||
                         ||  [1] Academic Paper / Research Dossier?         ||
                         ||  [2] Library API / Framework Implementation?    ||
                         ||  [3] Algorithm / Theoretical Bound Claim?       ||
                         ||  [4] Python Package / Dependency Specification? ||
                         ||  [5] Git Commit / Repository Source Truth?      ||
                         =====================================================
                               /            |          |          |          \
                              /             |          |          |           \
                             v              v          v          v            v
                 +---------------+ +------------+ +----------+ +--------+ +-------------+
                 |  1. arXiv     | | 2. Context7| |3.DeepWiki| |4. PyPI | | 5. GitHub   |
                 | (Doc Equality)| | (API Code) | |(Theories)| |(Wheels)| | (Source Code)|
                 +---------------+ +------------+ +----------+ +--------+ +-------------+
                 | • Paper text  | | • Method   | | • Proofs | | • JSON | | • Commit SHA|
                 | • Cosine sim  | |   signatures| | • Big-O  | |   API  | | • Tree diff |
                 | • Equation AST| | • Type hints | • State   | • Wheel  | • PR review  |
                 | • arXiv ID    | | • Kwargs   |   machines |   tags   | • Exact lines|
                 +---------------+ +------------+ +----------+ +--------+ +-------------+
                              \             |          |          |           /
                               \            |          |          |          /
                                v           v          v          v         v
                                +-------------------------------------------+
                                | STAGE 2: CLAIM LEDGER & CROSS-AUDIT       |
                                | - Compile verified evidence chunks        |
                                | - Eliminate unbacked claims               |
                                | - Compute fidelity score (0 - 100)        |
                                +-------------------------------------------+
                                                    |
                                                    v
                                +-------------------------------------------+
                                | STAGE 3: JEV SYSTEM ONE QUALITY GATE      |
                                | - Noul: passes_code_fidelity              |
                                | - Score: rubric_correctness (0.0 - 1.0)   |
                                | - Choice: APPROVED / NEEDS_REVISION       |
                                +-------------------------------------------+
                                                    |
                                                    v
                                         [ FINAL AUDIT SCORECARD ]
```

---

## 3. Deep Tool Specifications

### 3.1 arXiv Engine (`Arxiv` / `Arxic`) — Document Similarity & Equality Audit

**Objective**: Verify document originality, detect verbatim overlap, validate mathematical equation formulations, and ensure research dossiers cite authentic academic papers.

#### Capabilities & Audit Procedures:
1. **Document Equality & Overlap Metric**:
   - Calculates Jaccard distance over word $n$-grams ($n=3, 5$) and cosine similarity over dense chunk embeddings.
   - Equation AST Equivalence: Parses LaTeX equation strings via `sympy.parsing.latex` into symbolic trees to determine mathematical equality regardless of variable renaming.
2. **arXiv API Query Engine**:
   - Query endpoint: `http://export.arxiv.org/api/query?search_query=ti:<title_words>&max_results=5`.
   - Extracts canonical arXiv ID (`e.g., arXiv:2401.12345`), published date, author list, abstract, and DOI.
3. **Plagiarism & Citation Invariants**:
   - If a research dossier shares $>80\%$ structural sequence similarity with an arXiv paper without citing the exact arXiv ID, Judge issues a **REJECTED** verdict.

```python
# arXiv Query Recipe
import urllib.request
import xml.etree.ElementTree as ET

def verify_arxiv_paper(title_query: str) -> dict:
    url = f"http://export.arxiv.org/api/query?search_query=ti:{urllib.parse.quote(title_query)}&max_results=1"
    req = urllib.request.Request(url, headers={"User-Agent": "Swarm-Judge/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        tree = ET.fromstring(resp.read().decode("utf-8"))
        entry = tree.find("{http://www.w3.org/2005/Atom}entry")
        if entry is None:
            return {"verified": False, "reason": "Paper not found on arXiv"}
        return {
            "verified": True,
            "id": entry.find("{http://www.w3.org/2005/Atom}id").text,
            "title": entry.find("{http://www.w3.org/2005/Atom}title").text.strip(),
            "summary": entry.find("{http://www.w3.org/2005/Atom}summary").text.strip()[:200],
        }
```

---

### 3.2 Context7 Engine — Library & Framework Code Fidelity

**Objective**: Verify that code generated by `Coder`, `Refactor`, or `Optimizer` adheres 100% to the official library specification without hallucinating method names or arguments.

#### Capabilities & Audit Procedures:
1. **Library ID Resolution (`resolve-library-id`)**:
   - Maps module imports (e.g., `langgraph`, `pydantic`, `fastapi`, `numpy`, `torch`) to canonical package identifiers.
2. **Documentation Querying (`query-docs`)**:
   - Retrieves authoritative class interfaces, valid method parameters, return types, and version deprecations.
3. **Code Fidelity Verification**:
   - Compares the candidate AST against Context7's retrieved method signature.
   - **Hard Fail**: Any call passing an unknown keyword argument or invoking a deprecated API triggers immediate deduction in `rubric_correctness`.

```json
// Example Context7 MCP Execution
{
  "server": "context7",
  "tool": "resolve-library-id",
  "arguments": { "query": "langgraph" }
}
// Followed by:
{
  "server": "context7",
  "tool": "query-docs",
  "arguments": {
    "library_id": "langchain-ai/langgraph",
    "query": "StateGraph add_node add_edge compile"
  }
}
```

---

### 3.3 DeepWiki / Wikipedia Engine — Theoretical & Algorithmic Fidelity

**Objective**: Verify theoretical foundations, algorithmic proofs, state machine invariants, and asymptotic complexities.

#### Capabilities & Audit Procedures:
1. **Theoretical Validation**:
   - Verifies mathematical formulations (e.g., Kalman filtering, Bellman equations, Raft consensus invariants, Paxos leader election rules).
   - Validates asymptotic computational complexity ($O(1)$, $O(\log n)$, $O(n \log n)$).
2. **MediaWiki & Wikipedia API Access**:
   - Queries `https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exintro&explaintext&titles=<Concept>&format=json`.
3. **Nomenclature & Standard Checks**:
   - Ensures correct attribution of theorems (e.g., CAP theorem, Byzantine Generals Problem, Amdahl's Law).

---

### 3.4 PyPI Engine (`Pipy`) — Python Package & Wheel Verification

**Objective**: Verify that proposed Python packages exist, are actively maintained, have valid version numbers, and provide native binary wheels for macOS `darwin_x86_64`.

#### Capabilities & Audit Procedures:
1. **PyPI JSON Metadata Audit**:
   - Query endpoint: `https://pypi.org/pypi/<package-name>/json` or `https://pypi.org/pypi/<package-name>/<version>/json`.
   - Validates that the package actually exists on PyPI (preventing hallucinated names and typosquatting attacks).
2. **Binary Wheel Availability (`darwin_x86_64`)**:
   - Audits release distributions to ensure a pre-compiled wheel exists for the host environment (`macosx_*_x86_64.whl`).
   - If only an `.sdist` (`.tar.gz`) is available and requires custom C/C++ compilation, Judge checks whether local compilers (`LLVM 23.1.1` / Apple Clang 21) can build it without leaking Homebrew headers.
3. **Dependency Tree Consistency**:
   - Analyzes `requires_dist` fields to detect conflicting version constraints against `pyproject.toml`.

```python
# PyPI Package & Wheel Audit Recipe
import json
import urllib.request

def verify_pypi_package(pkg_name: str, min_version: str = "") -> dict:
    url = f"https://pypi.org/pypi/{pkg_name}/json"
    req = urllib.request.Request(url, headers={"User-Agent": "Swarm-Judge/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            info = data.get("info", {})
            releases = data.get("releases", {})
            latest_version = info.get("version", "")
            
            # Audit wheels for x86_64 macOS
            latest_files = releases.get(latest_version, [])
            has_mac_wheel = any("macosx" in f.get("filename", "") and "x86_64" in f.get("filename", "") for f in latest_files)
            has_universal_wheel = any("py3-none-any" in f.get("filename", "") for f in latest_files)

            return {
                "verified": True,
                "package": pkg_name,
                "latest_version": latest_version,
                "x86_64_compatible": has_mac_wheel or has_universal_wheel,
                "license": info.get("license", "Unknown"),
            }
    except urllib.error.HTTPError as e:
        return {"verified": False, "status_code": e.code, "error": f"Package '{pkg_name}' not found on PyPI"}
```

---

### 3.5 GitHub Engine — Source Code Implementation & Commit History Fidelity

**Objective**: Verify source code truth directly against canonical GitHub repositories, commit trees, pull requests, and real-world implementations.

#### Capabilities & Audit Procedures:
1. **Source Code Truth (`get_file_contents`)**:
   - Inspects canonical upstream repositories to verify whether a claimed bug, API signature, or pattern actually exists in the source code.
2. **Commit SHA & Tree Verification (`list_commits`, `get_commit`)**:
   - Validates that referenced commit SHAs exist and correspond to the claimed author, date, and commit message.
3. **Pull Request & Issue Auditing (`get_pull_request`, `list_issues`)**:
   - Inspects PR review comments, merge statuses, and resolved issues to prevent false claims of upstream resolution.

```json
// Example GitHub MCP Tool Call
{
  "server": "github",
  "tool": "get_file_contents",
  "arguments": {
    "owner": "langchain-ai",
    "repo": "langgraph",
    "path": "libs/langgraph/langgraph/graph/state.py"
  }
}
```

---

## 4. JEV System One Integration with Tools.md

When Judge queries these 5 verification engines, the resulting evidence is assembled into a structured JSON payload and submitted to **TypeSafe AI Jev System One**:

```json
{
  "model": "jev-latest",
  "context": {
    "target_name": "Coder_PR_42",
    "arxiv_equality_score": 0.05,
    "context7_fidelity_pass": true,
    "deepwiki_concept_valid": true,
    "pypi_wheel_verified": true,
    "github_commit_sha_valid": true
  },
  "questions": [
    {
      "id": "passes_code_fidelity",
      "type": "noul",
      "text": "Did the code pass 100% of Context7, PyPI, and GitHub fidelity checks without hallucinated APIs?"
    },
    {
      "id": "rubric_correctness",
      "type": "score",
      "text": "Score the technical accuracy and fidelity of the implementation from 0.0 to 1.0."
    },
    {
      "id": "fidelity_verdict",
      "type": "choice",
      "options": ["VERIFIED_CANONICAL", "NEEDS_FIDELITY_REVISION", "REJECTED_HALLUCINATION"]
    }
  ]
}
```

---

## 5. Verification Commands for CLI Execution

```bash
# 1. Audit Python package on PyPI
python3 -c 'import urllib.request, json; print(json.loads(urllib.request.urlopen("https://pypi.org/pypi/langgraph/json").read())["info"]["version"])'

# 2. Check arXiv document equality / query
python3 -c 'import urllib.request; print(urllib.request.urlopen("http://export.arxiv.org/api/query?search_query=ti:Attention+Is+All+You+Need&max_results=1").read().decode()[:300])'

# 3. Validate Judge agent manifest with new tooling capabilities
uv run python -m swarm_sdk.agents.validate
```
