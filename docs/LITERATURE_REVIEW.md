# 📚 Literature Review & Academic Debates — GraphRAG-Code

> [!IMPORTANT]
> This document synthesizes and critically analyzes academic papers and industry implementations directly relevant to the GraphRAG-Code architecture. The goal is to evaluate structural choices, compile benchmark data from primary sources, identify trade-offs, and map concrete enhancements.

---

## 1. Analyzed Literature Map

| # | Paper / Documentation | Authors / Organization | Year | Relevance |
|---|---|---|---|---|
| 1 | *Codebase-Memory: Tree-Sitter-Based Knowledge Graphs for LLM Code Exploration via MCP* | Vogel et al., [arXiv:2603.27277](https://arxiv.org/abs/2603.27277) (28 Mar 2026) | 2026 | ⭐⭐⭐⭐⭐ |
| 2 | *Rethinking Memory as Continuously Evolving Connectivity (FluxMem)* | Fang et al., [arXiv:2605.28773](https://arxiv.org/abs/2605.28773) — **inspiration only** (agent memory, not code retrieval) | 2026 | 💡 INSPIRATION |
| 3 | *Beyond Vector Similarity: Hierarchical Context-Aware Graph RAG* | Bhaumik et al., Google Cloud | 2026 | ⭐⭐⭐⭐⭐ |
| 4 | *Reliable Graph-RAG for Codebases: AST-Derived Graphs vs LLM-Extracted Knowledge Graphs* | Chinthareddy, arXiv:2601.08773 | Jan 2026 | ⭐⭐⭐⭐⭐ |
| 5 | *Practical Code RAG at Scale: Task-Aware Retrieval Design Choices under Compute Budgets* | Galimzyanov et al., JetBrains/NeurIPS 2025 | Oct 2025 | ⭐⭐⭐⭐⭐ |
| 6 | *How Aider's repomap uses PageRank to rank your codebase* | Paul Gauthier (Aider) | 2024 | ⭐⭐⭐⭐⭐ |
| 7 | *Personalized PageRank Estimation and Search: A Bidirectional Approach* | Lofgren et al., Stanford Univ. (WSDM) | 2016 | 💡 CONCEPTUAL INSPIRATION |

---

## 2. In-Depth Summary & Architectural Debates

---

### 2.0. Conceptual Inspiration: Bidirectional PPR (Lofgren et al., Stanford 2016) 💡

> [!IMPORTANT]
> **Honest attribution.** Lofgren et al.'s "Bidirectional PPR" is an *estimation algorithm*: it combines a forward push with a reverse random walk to **quickly approximate a single PPR value between two nodes** with provable error bounds. The paper's motivating use case is **Facebook name search** — e.g., given a network like Facebook, a query like *"people named John"*, and a searching user, return the top nodes (Abstract & Introduction). **Twitter-2010** (~1.5B edges) is a **benchmark dataset** used to test scalability, not the application domain.
>
> **GraphRAG-Code does NOT implement that algorithm.** What we implement is different and simpler: we run **two independent, full Personalized PageRank passes** — one on the original graph and one on the reversed graph — and then **merge the two score vectors with a tunable weight**. We borrow only the *concept* of reasoning along both edge directions, not Lofgren's estimator or its theoretical guarantees.

**Summary:** Lofgren et al. provide rigorous proofs for efficiently *estimating* PPR using a bidirectional forward-push + reverse-walk technique on massive graphs.

**Why it inspires GraphRAG-Code:**
The paper popularized the idea that valuable signal exists in *both* traversal directions of a directed graph. We map that intuition onto codebase logic, running PPR in each direction for a different purpose:
*   **Forward PPR (original graph):** Traces downstream dependencies ("What external functions does this logic rely on?").
*   **Backward PPR (reversed graph):** Traces upstream consumers to estimate "Blast Radius" ("Who calls this function, and what breaks if I change it?").

So we cite Lofgren et al. as conceptual inspiration for bidirectional reasoning — **not** as the mathematical foundation of our merge, which is a straightforward weighted combination of two standard PPR runs.

---

### 2.1. Codebase-Memory (Vogel et al., arXiv:2603.27277, 2026) 🔴 HIGHEST IMPORTANCE

**Authors & affiliations (from paper):**
- **Martin Vogel** — Independent Researcher, Berlin
- **Falk Meyer-Eschenbach** — Charité – Universitätsmedizin Berlin; Berlin Institute of Health (BIH); Humboldt University of Berlin
- **Severin Kohler** — Freie Universität Berlin; University Hospital Heidelberg
- **Elias Grünewald, Felix Balzer** — Charité – Universitätsmedizin Berlin

**Summary:** Tree-sitter knowledge graphs exposed via MCP, evaluated across **31 real-world repositories** and **66 languages**. Closest system parallel to GraphRAG-Code. Their graph agent uses **standard BFS / PageRank-style traversal**, not Personalized PageRank from a task-specific seed.

**Empirical Benchmarks (MCP Graph Agent vs. File Explorer Agent):**

| Metric | MCP (Graph) Agent | File Explorer Agent |
|---|---|---|
| **Answer quality score** | 0.83 | **0.92** |
| **Tool calls / question** | **2.3** | 4.8 |
| **Tokens / question** | **~1,000** | ~10,000 |
| **Query latency** | **<1 ms** | 10–30 s |

**Graph-native queries (important nuance):** For tasks such as **hub detection** and **caller ranking**, the graph agent *"matches or exceeds"* the explorer on **19 of 31 languages** — graph retrieval is **not uniformly worse**; it wins on structural query types even when overall quality score is lower.

**⚡ Key Architectural Debates:**

> [!WARNING]
> **THE ACCURACY GAP (aggregate):** Overall answer quality is **83% vs 92%** for the explorer. Graph-RAG trades a modest correctness gap for ~10× token savings and sub-millisecond query latency. Structural sub-tasks (hub/caller) are a different story — see 19/31 above.

**Gap vs. GraphRAG-Code — call resolution:** Codebase-Memory implements a **6-strategy call-resolution cascade** with confidence scores (0.95 → 0.30), including LSP-style type resolution for Go/C/C++. GraphRAG-Code currently uses **short_name matching** plus import heuristics. We may miss cross-file calls that their cascade resolves. See RESEARCH §3 *Threats to Validity*.

**Critical Questions for GraphRAG-Code:**
1. What is our tolerance for the 83% vs 92% aggregate gap vs. token/latency wins?
2. Vogel et al. use parallel worker pools; we index sequentially.
3. Community discovery (Louvain-style module grouping) is a feature we lack in v0.1.

**💡 Actionable Improvements:**
*   Measure PPR context vs. whole-file dumps on our own benchmark (not assume graph always wins).
*   Louvain / label propagation for module clusters (roadmap v0.5).
*   Long-term: multi-strategy call resolution (Phase 2+ / LSIF).

---

### 2.2. Aider RepoMap & PageRank (Paul Gauthier, 2024) 🟠 CORE VALIDATION

**Summary:** Official technical documentation explaining how Aider constructs its "Repo Map"—a compressed context map utilizing Tree-sitter tags and the PageRank algorithm to help LLMs understand codebase hierarchies without parsing entire files.

**Architectural Comparison:**

| Feature | Aider RepoMap | GraphRAG-Code (Ours) |
|---|---|---|
| **Graph Type** | Undirected (no direction) | **Directed** (call/import flows) |
| **Algorithm** | Standard PageRank | **Personalized PageRank** (seeded from active node) |
| **Output** | Ordered list of files/tags | **Source code snippets** of top-k symbols |
| **Persistence** | Regenerated per query | **SQLite** (incremental, persistent) |
| **MCP Interface** | ❌ No | ✅ Yes |

**⚡ Key Architectural Debates:**

> [!NOTE]
> Aider employs **Standard PageRank** (non-personalized). Consequently, PageRank scores are global—a widely used utility function like `logger.info` or `json.dumps` will always command a high score regardless of the specific task. GraphRAG-Code uses **Personalized PageRank (PPR)**: the seed nodes concentrate the teleportation probability, making the score strictly task-dependent. This is a **superior mathematical design** that we should heavily emphasize.

**Areas where Aider excels:**
*   Aider includes **function signatures** (names + parameter structures) in its context instead of just raw function bodies.
*   Aider implements a heuristic to prioritize **files active in the editor** ("active file boost").

**💡 Actionable Improvements:**
*   Add "Active File Boost": If the user is editing `bay_menu.py`, scale the personalization vector for all nodes inside that file path by x2.
*   Incorporate function signatures into symbol node database metadata.

---

### 2.3. Google Cloud HCRG (Bhaumik et al., 2026) 🔴 EVALUATION FRAMEWORK

**Summary:** Google Cloud deployed Tree-sitter, **Google Cloud Spanner Property Graphs**, and Gemini Context Caching for automated code migration (Java to Python microservices). They evaluated performance using 7 specialized metrics instead of conventional CodeBLEU.

**Standard RAG vs. Hierarchical Context-Aware Graph RAG (HCRG):**

| Metric | Standard RAG | Graph RAG (HCRG) | Delta (Δ) |
|---|---|---|---|
| **API Hallucination Rate** | 56.4% | **16.2%** | ↓ 40.2pp |
| **Dependency Resolution Quality** | 34.8% | **65.9%** | ↑ 31.1pp |
| **Parent-Child Consistency** | 26.7% | **45.5%** | ↑ 18.8pp |
| **CodeBLEU** | 91% | 91% | = (No Change ⚠️) |
| **Cyclomatic Complexity** | **71.6%** | 46.7% | ↓ 24.9pp ⚠️ |
| **Docstring Preservation** | **67.0%** | 61.0% | ↓ 6.0pp ⚠️ |

**⚡ Key Architectural Debates:**

> [!CAUTION]
> **GRAPH RAG TRIGGERS DEFENSIVE OVER-ENGINEERING**: When an LLM is fed too much structural dependency context, it tends to generate highly complex code to account for "safety," dropping Cyclomatic Complexity from 71.6% to 46.7%.
>
> **The Lesson:** Over-contextualization is harmful. Higher `top_k` limits are not always better.

**⚡ CodeBLEU caveat:**
CodeBLEU remained at 91% for both architectures despite the 40 percentage point difference in API hallucinations. This shows **CodeBLEU is insufficient on its own** for repository-scale structural quality. GraphRAG-Code should pair lexical metrics with structural measures such as DRQ, hallucination rate, and parent-child consistency.

**💡 Actionable Improvements:**
*   Implement "Context Density Control": If `top_k` returns code blocks exceeding $X$ tokens, automatically strip function bodies and return only signatures.
*   Construct a custom structural benchmarking suite (evaluating DRQ, hallucination rates, and PCC).

---

### 2.4. Reliable Graph-RAG: AST-Derived DKB vs. LLM-KB vs. No-Graph (Chinthareddy, Jan 2026) 🔴 CRITICAL EMPIRICAL PROOF

**Summary:** This paper compares 3 paradigms across 3 large Java repositories (Shopizer, ThingsBoard, OpenMRS Core) with 15 architectural tracing questions per repo (45 total):
*   **(A) No-Graph Naive RAG**: Vector-only top-k chunk retrieval.
*   **(B) LLM-KB**: LLM generates the dependency graph at index-time.
*   **(C) DKB (Deterministic Knowledge Base)**: Tree-sitter AST extraction with bidirectional graph traversal. It validates the same directional insight as GraphRAG-Code, though DKB uses fixed-depth BFS over Java type graphs while GraphRAG-Code uses PPR over Python symbol graphs.

**🏆 Correctness Benchmarks (45 questions, 3 repos):**

| Approach | Correct | Partial | Incorrect | Correctness Rate |
|---|---|---|---|---|
| **DKB (AST-derived)** | **43** | 2 | 0 | **95.6%** |
| LLM-KB | 38 | 5 | 2 | 84.4% |
| No-Graph (Vector-only) | 31 | 9 | 5 | 68.9% |

**Per-repository breakdown (15 questions each):**

| Repository | DKB (Ours-class) | LLM-KB | No-Graph |
|---|---|---|---|
| **Shopizer** | **15/15** | 13/15 | 6/15 |
| **ThingsBoard** | **14/15** | 12/15 | **14/15** |
| **OpenMRS Core** | **14/15** | 13/15 | 11/15 |

> [!CAUTION]
> **WORKLOAD-DEPENDENT, NOT UNIVERSAL:** On **ThingsBoard**, DKB **ties** the vector-only baseline (14/15 vs 14/15). The paper (§9.8) states gains are largest on suites emphasizing multi-hop architectural tracing and upstream discovery; on some repos the No-Graph baseline is already strong. **Claiming "DKB always beats No-Graph" is incorrect** — it is repository- and question-type-dependent.

**Shopizer highlight:** DKB **15/15** vs LLM-KB 13/15 vs No-Graph 6/15 — largest graph advantage.

**💰 Run-time Cost Analysis (Normalized, No-Graph = 1.0):**

| Workload | No-Graph | DKB (Ours) | LLM-KB |
|---|---|---|---|
| Shopizer (1 repo, 15 Qs) | $0.04 / 1.0× | $0.09 / **2.25×** | $0.79 / **19.75×** |
| OpenMRS + ThingsBoard (30 Qs) | $0.149 / 1.0× | $0.317 / **2.13×** | $6.80 / **45.64×** |

> [!CAUTION]
> **LLM-INDEXED KNOWLEDGE BASES ARE HIGH-RISK**: Indexing costs soar by 45x on larger codebases. More importantly, LLMs silently skipped **37.7% of files** during indexing (377/1210 files missed on Shopizer). This creates severe, unpredictable blind spots at query time. AST-derived DKBs avoid probabilistic file skipping, though implementation details can still affect chunk coverage and symbol mapping.

**⚡ Indexing Speed (Shopizer):**
*   No-Graph: 18.41s
*   **DKB (AST)**: 22.09s *(Only 3.68s over baseline!)*
*   LLM-KB: **215.09s** (10x slower than DKB)

**🔑 Key Technical Insights for GraphRAG-Code:**
1.  **Bidirectional traversal is mandatory.** Unidirectional successor traversal misses callers. The paper's Algorithm 1 uses *"Bidirectional expansion: for each retrieved class v, include both **successors** (downstream dependencies) and **predecessors** (upstream consumers)"* plus **interface-consumer expansion** when a class implements an interface. DKB uses **BFS** with fixed depth; GraphRAG-Code uses **PPR** with tunable merge weights — same directional insight, different ranking mechanism. This is **independent validation** of our backward-pass design.
2.  **Interface-consumer expansion is vital.** When class $C$ implements interface $I$, fetch all users of $I$ to bridge polymorphism (we implement this in `_get_expanded_seeds`).
3.  **LLM-KB suffers from a 27% node deficit** (842 nodes vs 1158 nodes in DKB on Shopizer).

**⚡ PPR vs. Bidirectional BFS Debate:**

> [!NOTE]
> DKB implements **BFS bidirectional traversal with fixed depth limits** (successors + predecessors). GraphRAG-Code utilizes **Personalized PageRank (PPR)**. PPR dynamically scores relevance globally based on link structure rather than flat BFS limits. However, DKB's explicit **interface-consumer expansion** is exceptionally robust. A practical next step is to combine PPR ranking with deterministic interface-consumer expansion and evaluate that hybrid directly.

---

### 2.5. JetBrains Task-Aware Retrieval (NeurIPS 2025) 🟢 PRACTICAL METRIC GUIDE

**Summary:** JetBrains Research evaluated various RAG architectures across the Long Code Arena dataset on two complementary tasks:
*   **Code Completion (PL→PL)**: Generating the next lines of code given surrounding syntax.
*   **Bug Localization (NL→PL)**: Pinpointing buggy source files from natural language issue reports.

**📊 Empirical Performance Data:**

*Task Code Completion (PL→PL) — Exact Match:*

| Scorer | Splitter | EM @4K ctx | EM @16K ctx | Latency/1M symbols |
|---|---|---|---|---|
| **BM25** | **word** | **0.55** | **0.60** | 0.2s |
| BM25 | token/BPE | 0.50 | 0.59 | 2.0s (10x slower) |
| IoU | line | 0.46 | 0.57 | 0.02s |
| Dense E5-large | — | 0.39 | 0.52 | 3.3s |
| Path distance | — | 0.37 | 0.55 | 0.0005s |

*Task Bug Localization (NL→PL) — NDCG:*

| Model | NDCG (mean) | Latency |
|---|---|---|
| **Voyager-3-code** | **0.717** | 19.0s/1M |
| E5-large | 0.590 | 2.8s/1M |
| **BM25 word** | **0.574** | **0.07s/1M** |

**⚡ 5 Actionable Insights for GraphRAG-Code:**

> [!IMPORTANT]
> **Insight #1: Task-dependent retrieval is mandatory.** No single configuration works for all tasks. PL→PL requires syntax-dense local context (BM25/IoU). NL→PL requires dense embedding retrieval. Graph/PPR excels at structural multi-hop tracing.
>
> **Insight #2: BPE splitting is an anti-pattern.** It is 10x slower than word-splitting with zero accuracy gain.
>
> **Insight #3: Match chunk sizes to context windows:**
> *   $\le$ 4K context: 32-64 lines
> *   4K - 8K context: 64-128 lines
> *   $\ge$ 16K context: Whole-file retrieval is superior to chunking.
>
> **Insight #4: Simple line-splitting matches syntax-aware chunking** in retrieval performance. Avoid over-engineering complex syntax-based line splitting algorithms.
>
> **Insight #5:** Prepend Graph context, then backfill with BM25 to achieve optimal retrieval efficiency.

---

### 2.6. FluxMem (Fang et al., arXiv:2605.28773, 2026) 💡 INSPIRATION ONLY

> [!NOTE]
> **Not code-graph evidence.** FluxMem is an **agent memory framework** (continuously evolving connectivity between memory nodes). It does **not** benchmark code retrieval, AST graphs, or MCP codebase exploration. Cite it as **design inspiration** for future adaptive edge weights — **not** as empirical support for GraphRAG-Code's structural retrieval performance.

**Summary:** Proposes *Memory-as-Connectivity* — memory as an evolving topology rather than static chunks, with self-repairing connectivity and benchmarks on agent tasks (LoCoMo, Mind2Web, GAIA).

**Relevance to GraphRAG-Code (roadmap only):**
*   **Phase 3+ idea:** Adjust PPR edge weights from agent session feedback (which paths led to successful edits) — *inspired by* FluxMem's connectivity evolution, applied only to **weights**, not to AST facts (the graph structure stays deterministic).
*   **Do not claim:** "FluxMem proves our code graph works" — it addresses a different problem (long-horizon agent memory).

---

## 3. Consensus & Debate Matrix

### 3.1. Industry Consensus (Validates GraphRAG-Code)

*   **AST-based parsing** is the most reliable low-cost backbone for mapping complex codebase hierarchies in the cited systems (Vogel, Google Cloud, Reliable Graph-RAG).
*   **Graph RAG reduces API hallucinations** by up to 40% compared to vector search (Google Cloud).
*   **Graph traversal and ranking** deliver structural, multi-hop context more efficiently than pure vector embeddings for architectural queries; GraphRAG-Code's differentiator is making that ranking **Personalized** to the seed symbol.
*   **MCP** is the correct protocol standard for AI Agent tool integration.

### 3.2. Ongoing Scientific Debates

| Debate Point | Pro-Graph Side | Counter-Argument / Baseline |
|---|---|---|
| **Are graphs always more accurate?** | DKB 95.6% aggregate (Reliable RAG); graph wins big on Shopizer (15/15 vs 6/15). | Vogel: aggregate 83% vs 92% explorer; **but** graph matches/exceeds on hub/caller tasks on **19/31** langs. ThingsBoard: DKB **ties** No-Graph (14/15). |
| **PPR vs. Bidirectional BFS** | PPR naturally ranks dynamic mathematical relevance. | BFS enforces clear, guaranteed interface-boundary expansion. |
| **Does graph context over-engineer?** | Structural RAG eliminates invalid calls. | Google HCRG shows it triggers highly defensive complexity. |
| **BM25 vs. Dense vs. Graph** | Graph-RAG rules complex multi-hop. | JetBrains shows BM25 is 200x faster for basic completions. |

---

## 4. GraphRAG-Code Competitive Positioning

| Feature | Codebase-Memory (Vogel et al.) | Aider RepoMap | GraphRAG-Code (Ours) |
|---|---|---|---|
| **Multi-Language** | 66 Languages | 20+ Languages | 1 Language (Python) |
| **Traversal / Ranking** | Standard BFS / PageRank | Standard PageRank | ✅ **Personalized PageRank** (seeded) |
| **Call Resolution** | ✅ 6-strategy cascade (0.95→0.30) | ❌ Tag-based | ⚠️ short_name + import heuristics |
| **Source Extraction** | ❌ Metadata-only | ❌ Filenames/Tags only | ✅ **Full Code Snippets** |
| **Interface Expansion** | ❌ No | ❌ No | ✅ **Dynamic Seeds (extends)** |
| **Persistence** | SQLite | ❌ None | ✅ **Incremental SQLite** |
