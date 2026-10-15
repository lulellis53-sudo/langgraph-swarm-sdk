# Agent Memory: FileManager

> **Agent Memory Ledger**: Local episodic, semantic, and format checkpoint memory store for `FileManager`.
> **Architecture**: Multi-tier memory model (Short-term context, Episodic interaction history, Semantic cache).

---

## 1. Memory Store Architecture

- **Episodic Memory**: Tracks extraction checksums, file paths, and format conversion ledgers.
- **Semantic Cache**: Persists parsed binary signatures, magic numbers, and schema definitions.
- **Checkpoint Ledger**: Rollback snapshots before in-place format conversions.

---

## 2. Invariants & Isolation

1. **Zero Secret Leakage**: No credentials or private tokens stored in memory.
2. **Deterministic Pruning**: Context is pruned or summarized when episodic history exceeds token thresholds.
3. **Audit Trail**: Every stored entry includes an execution timestamp, task ID, source format, target format, and checksum.
