# CodeGraph Public Roadmap

This document outlines the high-level roadmap for the CodeGraph open-source ecosystem. We welcome community feedback, feature requests, and academic collaboration.

---

## 🗺️ High-Level Gantt Schedule

```mermaid
gantt
    title CodeGraph Evolution Phases
    dateFormat  YYYY-MM-DD
    section Public Alpha
    v0.1.0-alpha Polish & Launch :active, 2026-05-31, 2d
    section Future Milestones
    v0.2.0: Usable Multi-Language OSS : 2026-06-02, 25d
    v0.3.0: Academic Ablation & Paper Draft : 2026-06-27, 30d
    v0.5.0: Production Packaging & Watch Mode : 2026-07-27, 30d
    v1.0.0: Enterprise & Intent Routing : 2026-08-27, 60d
```

---

## 🚀 Execution Phases

### Phase 1: GitHub Alpha Release (v0.1.0-alpha) — **[COMPLETED]**
*   **Deliverables:**
    1.  **Repository Cleanup:** Establish clean `.gitignore`, remove raw dev caches, and streamline standard dependencies.
    2.  **Path & API Hardening:** Fix tree-sitter v0.23+ compatibility via `QueryCursor` and deploy **Dynamic Path Resolution** for stdio MCP sub-shells.
    3.  **Stdio Isolation:** Migrate all stdout `print()` logs inside the MCP Server and Core Engine to standard `logging` piped directly to `sys.stderr` to prevent JSON-RPC stream contamination.
    4.  **Academic Positioning:** Publish `docs/RESEARCH.md` detailing how Bidirectional Personalized PageRank merges both blast radius and implementation context within 90%+ token savings.

### Phase 2: Usable Multi-Language OSS (v0.2.0) — *Est: June 2026*
*   **Target Deliverables:**
    1.  **Multi-Language AST Support:** Add tree-sitter static parsing configurations for TypeScript/JavaScript and Java.
    2.  **Active File Boost:** Boost personalized weights dynamically for nodes belonging to files currently focused in active IDE windows.
    3.  **Basic Semantic Resolution:** Resolve explicit cross-file imports and parameter type annotations to minimize graph connectivity gaps.
    4.  **Community Evaluation:** Benchmark CodeGraph metrics on $\ge$ 5 real-world open-source repositories.

### Phase 3: Academic Ablation & Research Positioning (v0.3.0) — *Est: July 2026*
*   **Target Deliverables:**
    1.  **Ablation Study:** Conduct rigorous evaluations evaluating retrieval precision@k across weight distributions `0.0`, `0.5`, `0.7`, `1.0` for B-PPR.
    2.  **Systematic Error Log:** Candidly document edge cases (e.g., dynamic imports, decorators) where structural indexing fails.
    3.  **Academic Preprint Draft:** Complete a 6–8 page research manuscript highlighting local-first ast-derived graph advantages over LLM-generated indexing.

### Phase 4: Production Packaging (v0.5.0) — *Est: August 2026*
*   **Target Deliverables:**
    1.  **PyPI Release:** Package modular `codegraph-core` structure and publish to public repositories.
    2.  **Incremental Watch Mode:** Setup persistent file-system watching (`watchdog`) to update graph caches instantly.
    3.  **Module Clustering:** Run Louvain or Leiden community detection to bundle large code graphs into human-navigable module groups.

### Phase 5: Enterprise Scaling & Hybrid RAG (v1.0.0) — *Est: Q4 2026 (Stretch Goal)*
*   **Target Deliverables:**
    1.  **Intent Router:** Set up a lightweight router that maps pure PL$\rightarrow$PL code completion tasks directly to BM25, and structural/architectural queries to B-PPR.
    2.  **Centralized Multi-Repo Sync:** Sync sqlite graphs to a centralized PostgreSQL registry to support cross-service microservice blast-radius evaluations.
