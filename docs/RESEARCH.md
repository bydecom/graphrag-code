# Research Positioning & Limitations

This document serves as the academic positioning and a critical evaluation of the GraphRAG-Code prototype. It outlines the specific research questions addressed, contextualizes our approach against current state-of-the-art literature, and candidly discusses the system's limitations.

## 1. Research Question & Problem Statement

**Problem:** Standard Code RAG relying solely on vector similarity (e.g., embeddings) struggles with *structural queries* (e.g., "What is the blast radius of modifying function X?" or "Find all functions that call Y"). Sending the entire codebase to an LLM context window is cost-prohibitive and can induce hallucination or defensive over-engineering.

**Question:** Can we deterministically extract a precise, token-efficient, and structurally coherent implementation context using an AST-derived graph combined with Bidirectional Personalized PageRank, without incurring the high indexing costs of LLM-generated graphs?

## 2. Academic Positioning

In the current landscape of Agentic Graph-RAG (2025-2026), GraphRAG-Code is positioned as an **engineering extension** of two prominent research lines:

1. **Aider's Repo Map (2024):** Aider uses standard PageRank over a Tree-Sitter AST graph. However, standard PageRank measures *global popularity* (e.g., a utility function will always score high), which may not capture task-specific relevance. GraphRAG-Code applies **Personalized PageRank (PPR)** where energy propagates outwards from the *active seed node*, ranking files based on relevance to the specific task rather than global popularity.
2. **Reliable Graph-RAG (Chinthareddy, [arXiv:2601.08773](https://arxiv.org/abs/2601.08773), Jan 2026):** AST-derived Deterministic Knowledge Bases (DKB) outperform LLM-built graphs on aggregate architectural tracing (43/45 correct vs 38/45 LLM-KB vs 31/45 No-Graph), but gains are **workload-dependent** — on ThingsBoard, DKB **ties** the vector baseline (14/15 each). The paper's bidirectional expansion (successors + predecessors, plus interface-consumer expansion) independently validates our backward-pass design; we implement the same directional insight via **PPR merge** rather than fixed-depth BFS.
3. **Codebase-Memory (Vogel et al., [arXiv:2603.27277](https://arxiv.org/abs/2603.27277), Mar 2026):** Closest MCP + Tree-sitter parallel. Aggregate answer quality favors the file explorer (0.92 vs 0.83), but the graph agent wins on **hub detection / caller ranking** on 19/31 languages and uses ~10× fewer tokens. They use standard BFS/PageRank; we add **Personalized** PPR and source snippets.

GraphRAG-Code also runs **two independent Personalized PageRank passes** — Forward PPR on the graph (downstream dependencies) and Backward PPR on a reversed graph (upstream callers/impact) — merged with a tunable `backward_weight`. This is *not* Lofgren et al.'s (2016) bidirectional PPR *estimator* (whose motivating use case is **Facebook name search**, benchmarked on the Twitter-2010 graph); we borrow only the concept of reasoning along both edge directions. Because a pure caller has near-zero forward score, the weight selects between two practical modes: default `0.2` favours downstream context; `0.9` (`get_impact`) surfaces blast radius.

*Positioning Statement:* GraphRAG-Code extends the Aider RepoMap and Codebase-Memory paradigms by merging two directional Personalized PageRank passes into weight-selectable query modes, extracting exact source code blocks in $O(1)$ disk I/O, and exposing the graph to IDE agents via standard Model Context Protocol (MCP) tools.

## 3. Trade-offs and Limitations

To transition from a "solid engineering prototype" to a novel academic contribution, several limitations must be acknowledged and addressed in future iterations:

- **Syntax vs. Semantics:** Tree-sitter provides syntax-level parsing. Without deep static analysis (like LSIF or SCIP), relationships such as `obj.method()` cannot be deterministically resolved if `obj`'s type is unknown. Decorators, metaclasses, and dynamic imports represent blind spots in the graph.
- **Call resolution gap (vs. Codebase-Memory):** Vogel et al. use a **6-strategy call-resolution cascade** with confidence scores (0.95→0.30), including LSP-style resolution for Go/C/C++. GraphRAG-Code uses **short_name matching** plus import heuristics. Cross-file calls that lack a resolvable import may be missed or ambiguous.
- **Accuracy vs. Efficiency Trade-off:** Codebase-Memory reports aggregate answer quality **0.83 (graph) vs 0.92 (file explorer)**, with ~10× token savings — but graph **matches or exceeds** the explorer on hub/caller tasks on **19/31 languages**. Chinthareddy (2026) shows DKB at **95.6% aggregate** yet **ties** No-Graph on ThingsBoard (14/15). Graph-RAG is not uniformly superior; GraphRAG-Code must measure its own trade-off on structural tasks.
- **Hyperparameter Dependency:** The `backward_weight` parameter (default 0.2) is a heuristic. A sweep is provided in [`ablation_runner.py`](../ablation_runner.py), and §4 shows the two endpoint weights (0.9 / 0.3) behave as intended on retrieval; a fuller optimal-balance study across repos is still pending.
- **Need for Hybrid Search:** Graph RAG dominates structural queries, but BM25 or Dense Vector search is still superior for simple PL$\rightarrow$PL code completion tasks. A future intent router is required.
- **FluxMem (inspiration only):** [arXiv:2605.28773](https://arxiv.org/abs/2605.28773) motivates *adaptive edge weights* from agent feedback in future phases — it does **not** benchmark code-graph retrieval and must not be cited as performance evidence.

## 4. RQ1 — Structural Retrieval Quality (Deterministic, LLM-free)

This first evaluation isolates **retrieval quality** from any LLM. It answers:
*does Bidirectional PPR surface the structurally-relevant symbols better than
naive neighbour expansion or a single-direction PageRank?* Because there is no
language model in the loop, the result cannot suffer from LLM-as-judge
*self-preference bias* — the ground truth and the metric are purely mathematical.

**Why this is not self-graded bias.** The ground truth is the **transitive
closure** of the dependency graph (if A calls B and B calls C, then C is in the
blast radius of A). This is a graph-theoretic fact, identical whether computed by
a human or a machine, and it is derived *independently* of any ranking method.
The arms are deterministic algorithms (PageRank / degree sort), and the scores are
standard IR metrics (Recall@k / Precision@k). The only deliberate design choice is
selecting tasks that expose each algorithm's behaviour — which is exactly how
ablations are framed in the code-graph literature.

### 4.1 Methodology

- **Harness:** [`eval_retrieval.py`](../eval_retrieval.py) (reproducible, offline).
- **Reproduce:** `python eval_retrieval.py --codebase-dir src --task both --k "3,5,10" --num-seeds 15`
- **Graph under test:** the tool's own `src/` (self-indexed), **38 nodes / 65 edges**.
- **Seeds:** top-degree symbols per task (most callers for blast radius, most
  callees for dependencies), so each seed has a non-trivial ground truth.
- **Arms:**
  - `brute_force` — direct (1-hop) neighbours only, ranked by node degree.
  - `uni_directional` — forward-only PPR (`backward_weight = 0.0`).
  - `bi_directional` — the shipped engine (`engine.get_context_ppr`), with the
    same weights the MCP tools use (`IMPACT = 0.9`, `CONTEXT = 0.3`).

### 4.2 Results

> ⚠️ **Status note (honesty):** the tables below are on the tool's own 38-node
> `src/` graph and are **illustrative of the mechanism, not generalisable**.
> Runs on real packages (`requests`, `click`) show that (a) full-closure
> Recall@k is dominated by closure size on larger graphs and should not be
> headlined, and (b) the durable signal is **precision** — `uni_directional`
> degrades to 0.27–0.64 Precision@10 while `bi_directional` holds ~0.98. A
> proper multi-repo write-up (precision-first, with a multi-hop-capable baseline)
> will replace these toy numbers as the single source of truth. See README → RQ1.

**Task: `blast_radius`** (relevant = transitive callers; `backward_weight = 0.9`)

| Arm | Recall@3 | Recall@5 | Recall@10 |
|-----|----------|----------|-----------|
| `brute_force` | 0.729 | 0.751 | 0.762 |
| `uni_directional` | 0.000 | 0.000 | 0.000 |
| **`bi_directional`** | **0.840** | **0.978** | **1.000** |

**Task: `dependencies`** (relevant = transitive callees; `backward_weight = 0.3`)

| Arm | Recall@3 | Recall@5 | Recall@10 |
|-----|----------|----------|-----------|
| `brute_force` | 0.744 | 0.759 | 0.789 |
| `uni_directional` | 0.889 | 0.959 | 1.000 |
| `bi_directional` | 0.889 | 0.959 | 1.000 |

### 4.3 Interpretation

- **The backward pass is necessary, not decorative.** On blast radius,
  `uni_directional` scores **0.000** at every k: a pure caller has ~zero forward
  PPR score, so a forward-only retriever is *structurally blind* to upstream
  impact. This is the empirical justification for the bidirectional merge.
- **Brute force is capped by 1-hop reach.** It plateaus (~0.76–0.79 Recall@10)
  because multi-hop callers/callees are invisible to it — the exact gap a ranked
  graph traversal closes.
- **Honest null result on dependencies.** For downstream queries, forward PPR
  alone is already optimal, and bidirectional ties it (does no harm). The value of
  the second direction is concentrated in **blast radius**, which is precisely the
  query mode that differentiates `get_impact` / `plan_change` from flat BFS tools.

### 4.4 Threats to Validity / Next Steps

- **Small graph.** These numbers are on a single small codebase (38 nodes). They
  validate the *mechanism and the harness*, not generalisation. Multi-repo runs
  (`requests`, `httpx`, `fastapi`, plus a private app) are the next step and will
  be appended here as the single source of truth.
- **Ground truth = all structural edges.** The closure currently includes
  `contains`/`import` edges as well as `call`/`extends`. An edge-type-filtered
  variant is a planned refinement.
- **Pending baseline:** BM25 / lexical chunking, to bound where lexical retrieval
  beats structural (motivating the future intent router).
- **Call resolution gap:** Same caveat as §3 — short_name matching may under-count
  edges that Codebase-Memory's 6-strategy cascade would resolve; precision/recall
  on real repos may improve once call resolution hardens.
- **External literature caveat:** Chinthareddy (2026) shows DKB **ties** No-Graph on
  ThingsBoard (14/15). Graph advantages are **workload-dependent**; our RQ1 harness
  measures structural retrieval only, not end-to-end LLM answer quality.

## 5. Evaluation Roadmap (Future Work)

To validate the academic efficacy of GraphRAG-Code, the following benchmarks must be conducted:
1. **Rigor Benchmark:** Run RQ1 (`eval_retrieval.py`) on $\ge$ 10 varied open-source repositories and aggregate.
2. **Baselines:** Compare against (A) Full-file brute force, (B) Unidirectional PPR ✅ *(done, see §4)*, and (C) BM25 chunking *(pending)*.
3. **Metrics:** Measure Token Savings, Latency, and custom structural metrics such as Dependency Resolution Quality (DRQ) and API Hallucination Rate, rather than generic metrics like CodeBLEU.
