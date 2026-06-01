# 📚 Literature Review & Academic Debates — GraphRAG-Code

> [!IMPORTANT]
> This document synthesizes and critically analyzes 6 academic papers and industry implementations directly relevant to the GraphRAG-Code architecture. The goal is to evaluate structural choices, compile hard benchmark data, identify trade-offs, and map out concrete enhancements.

---

## 1. Analyzed Literature Map

| # | Paper / Documentation | Authors / Organization | Year | Relevance |
|---|---|---|---|---|
| 1 | *Codebase-Memory: Tree-Sitter-Based Knowledge Graphs for LLM Code Exploration via MCP* | Vogel et al., Charité Berlin | 2026 | ⭐⭐⭐⭐⭐ |
| 2 | *Rethinking Memory as Continuously Evolving Connectivity (FluxMem)* | Fang et al., Zhejiang/Alibaba | 2026 | ⭐⭐⭐⭐ |
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
> **Honest attribution.** Lofgren et al.'s "Bidirectional PPR" is an *estimation algorithm*: it combines a forward push with a reverse random walk to **quickly approximate a single PPR value between two nodes** with provable error bounds, primarily to scale "Name Search" on massive social graphs (e.g., Twitter).
>
> **GraphRAG-Code does NOT implement that algorithm.** What we implement is different and simpler: we run **two independent, full Personalized PageRank passes** — one on the original graph and one on the reversed graph — and then **merge the two score vectors with a tunable weight**. We borrow only the *concept* of reasoning along both edge directions, not Lofgren's estimator or its theoretical guarantees.

**Summary:** Lofgren et al. provide rigorous proofs for efficiently *estimating* PPR using a bidirectional forward-push + reverse-walk technique on massive graphs.

**Why it inspires GraphRAG-Code:**
The paper popularized the idea that valuable signal exists in *both* traversal directions of a directed graph. We map that intuition onto codebase logic, running PPR in each direction for a different purpose:
*   **Forward PPR (original graph):** Traces downstream dependencies ("What external functions does this logic rely on?").
*   **Backward PPR (reversed graph):** Traces upstream consumers to estimate "Blast Radius" ("Who calls this function, and what breaks if I change it?").

So we cite Lofgren et al. as conceptual inspiration for bidirectional reasoning — **not** as the mathematical foundation of our merge, which is a straightforward weighted combination of two standard PPR runs.

---

### 2.1. Codebase-Memory (Vogel et al., 2026) 🔴 HIGHEST IMPORTANCE

**Summary:** The research team from Charité Berlin built an architecture closely resembling ours: parsing 66 languages using Tree-sitter and exposing the resulting codebase knowledge graph via an MCP server. They evaluated the framework across 31 real-world repositories.

**Empirical Benchmarks:**

| Metric | File Explorer Agent | Codebase-Memory (Graph) |
|---|---|---|
| **Answer Quality** | **92%** | 83% |
| **Token Consumption** | Baseline 1x | **10x Less** |
| **Tool Calls** | Baseline 1x | **2.1x Less** |
| **Hub Detection** | Inferior | **Superior/Equal on 19/31 repos** |

**⚡ Key Architectural Debates:**

> [!WARNING]
> **THE ACCURACY GAP**: The Graph-based system achieved **83% quality** compared to the brute-force File Explorer's **92%**. This implies that **Graph-RAG is not always superior to brute-force file dumping in terms of pure correctness!** However, it offers a monumental 10x token saving.

**Critical Questions for GraphRAG-Code:**
1. We are trading off a minor degree of **accuracy** for a massive gain in **efficiency**. What is our target tolerance threshold for accuracy loss?
2. Vogel et al. utilize "parallel worker pools" and "call-graph traversal" which we currently execute sequentially.
3. "Community discovery" (grouping modular code clusters) is a major feature GraphRAG-Code v0.1 lacks.

**💡 Actionable Improvements:**
*   Establish empirical correctness benchmarks: Measure the accuracy of PPR context extraction against raw whole-file context dumps.
*   Implement community detection (e.g., Louvain or Label Propagation via `rustworkx`) to bridge the 83% -> 92% quality gap.

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

**⚡ CodeBLEU Debunked:**
CodeBLEU remained at 91% for both architectures despite the 40 percentage point difference in API hallucinations. This proves **CodeBLEU is a useless metric** for code generation quality. GraphRAG-Code must adopt Google's custom structural evaluation approach.

**💡 Actionable Improvements:**
*   Implement "Context Density Control": If `top_k` returns code blocks exceeding $X$ tokens, automatically strip function bodies and return only signatures.
*   Construct a custom structural benchmarking suite (evaluating DRQ, hallucination rates, and PCC).

---

### 2.4. Reliable Graph-RAG: AST-Derived DKB vs. LLM-KB vs. No-Graph (Chinthareddy, Jan 2026) 🔴 CRITICAL EMPIRICAL PROOF

**Summary:** This paper compares 3 paradigms across 3 large Java repositories (Shopizer, ThingsBoard, OpenMRS Core) with 15 architectural tracing questions per repo (45 total):
*   **(A) No-Graph Naive RAG**: Vector-only top-k chunk retrieval.
*   **(B) LLM-KB**: LLM generates the dependency graph at index-time.
*   **(C) DKB (Deterministic Knowledge Base)**: Tree-sitter AST extraction with bidirectional graph traversal (**identical to our approach**).

**🏆 Correctness Benchmarks (45 questions, 3 repos):**

| Approach | Correct | Partial | Incorrect | Correctness Rate |
|---|---|---|---|---|
| **DKB (AST-derived)** | **43** | 2 | 0 | **95.6%** |
| LLM-KB | 38 | 5 | 2 | 84.4% |
| No-Graph (Vector-only) | 31 | 9 | 5 | 68.9% |

**Shopizer Sub-test (15 questions):** DKB **15/15** ✅ | LLM-KB 13/15 | No-Graph 6/15

**💰 Run-time Cost Analysis (Normalized, No-Graph = 1.0):**

| Workload | No-Graph | DKB (Ours) | LLM-KB |
|---|---|---|---|
| Shopizer (1 repo, 15 Qs) | $0.04 / 1.0× | $0.09 / **2.25×** | $0.79 / **19.75×** |
| OpenMRS + ThingsBoard (30 Qs) | $0.149 / 1.0× | $0.317 / **2.13×** | $6.80 / **45.64×** |

> [!CAUTION]
> **LLM-INDEXED KNOWLEDGE BASES ARE HIGH-RISK**: Indexing costs soar by 45x on larger codebases. More importantly, LLMs silently skipped **37.7% of files** during indexing (377/1210 files missed on Shopizer). This creates severe, unpredictable blind spots at query time. AST-derived DKBs guarantee 100% file coverage.

**⚡ Indexing Speed (Shopizer):**
*   No-Graph: 18.41s
*   **DKB (AST)**: 22.09s *(Only 3.68s over baseline!)*
*   LLM-KB: **215.09s** (10x slower than DKB)

**🔑 Key Technical Insights for GraphRAG-Code:**
1.  **Bidirectional traversal is mandatory.** Unidirectional successor traversal completely misses callers.
2.  **Interface-consumer expansion is vital.** When class $C$ implements interface $I$, we must fetch all users of $I$ to bridge polymorphic boundaries. This is why DKB scored 15/15 while LLM-KB fell to 13/15.
3.  **LLM-KB suffers from a 27% node deficit** (842 nodes vs 1158 nodes in DKB).

**⚡ PPR vs. Bidirectional BFS Debate:**

> [!NOTE]
> DKB implements **BFS bidirectional traversal with fixed depth limits** (successors + predecessors). GraphRAG-Code utilizes **Personalized PageRank (PPR)**. PPR dynamically scores relevance globally based on link structure rather than flat BFS limits. However, DKB's explicit **interface-consumer expansion** is exceptionally robust. Hybridizing PPR with interface-consumer expansion represents the state-of-the-art.

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
> **Insight #5: Prepend Graph context, then backfill with BM25** to achieve optimal retrieval efficiency.

---

## 3. Consensus & Debate Matrix

### 3.1. Industry Consensus (Validates GraphRAG-Code)

*   **AST-based parsing** is the only reliable way to map complex codebase hierarchies (Vogel, Google Cloud, Reliable Graph-RAG).
*   **Graph RAG reduces API hallucinations** by up to 40% compared to vector search (Google Cloud).
*   **Personalized PageRank** delivers structural, multi-hop context far more efficiently than vector embeddings (Aider, Vogel).
*   **MCP** is the correct protocol standard for AI Agent tool integration.

### 3.2. Ongoing Scientific Debates

| Debate Point | Pro-Graph Side | Counter-Argument / Baseline |
|---|---|---|
| **Are graphs always more accurate?** | DKB achieves 95.6% correctness (Reliable RAG). | Vogel et al. show Graph (83%) < File Explorer (92%). |
| **PPR vs. Bidirectional BFS** | PPR naturally ranks dynamic mathematical relevance. | BFS enforces clear, guaranteed interface-boundary expansion. |
| **Does graph context over-engineer?** | Structural RAG eliminates invalid calls. | Google HCRG shows it triggers highly defensive complexity. |
| **BM25 vs. Dense vs. Graph** | Graph-RAG rules complex multi-hop. | JetBrains shows BM25 is 200x faster for basic completions. |

---

## 4. GraphRAG-Code Competitive Positioning

| Feature | Codebase-Memory (Berlin) | Aider RepoMap | GraphRAG-Code (Ours) |
|---|---|---|---|
| **Multi-Language** | 66 Languages | 20+ Languages | 1 Language (Python) |
| **PPR Personalization** | ❌ Standard PageRank | ❌ Standard PageRank | ✅ **Personalized PageRank** |
| **Source Extraction** | ❌ Metadata-only | ❌ Filenames/Tags only | ✅ **Full Code Snippets** |
| **Interface Expansion** | ❌ No | ❌ No | ✅ **Dynamic Seeds (extends)** |
| **Persistence** | SQLite | ❌ None | ✅ **Incremental SQLite** |
```
