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
- **Hyperparameter Dependency:** The `backward_weight` parameter (default 0.2) is a heuristic. A sweep is provided in [`ablation_runner.py`](../ablation_runner.py); [§4](#4-rq1--structural-retrieval-quality-deterministic-llm-free) documents precision results at the shipped endpoint weights (0.9 / 0.3). A fuller optimal-balance study across repos is still pending.
- **Need for Hybrid Search:** Graph RAG dominates structural queries, but BM25 or Dense Vector search is still superior for simple PL$\rightarrow$PL code completion tasks. A future intent router is required.
- **FluxMem (inspiration only):** [arXiv:2605.28773](https://arxiv.org/abs/2605.28773) motivates *adaptive edge weights* from agent feedback in future phases — it does **not** benchmark code-graph retrieval and must not be cited as performance evidence.

## 4. RQ1 — Structural Retrieval Quality (Deterministic, LLM-free)

This evaluation isolates **retrieval quality** from any LLM. It answers:
*does Bidirectional PPR surface the structurally-relevant symbols better than
naive neighbour expansion or a single-direction PageRank?* Because there is no
language model in the loop, the result cannot suffer from LLM-as-judge
*self-preference bias* — the ground truth and the metric are purely mathematical.

**Why this is not self-graded bias.** The ground truth is the **transitive
closure** of the indexed dependency graph (if A calls B and B calls C, then C is
in the blast radius of A). This is a graph-theoretic fact, derived independently
of any ranking method. The arms are deterministic algorithms; `bi_directional`
calls the **same** `engine.get_context_ppr` code path that ships in the MCP
server, so the benchmark measures what users receive, not a reimplemented variant.

### 4.1 Methodology

| Item | Definition |
|------|------------|
| **Harness** | [`eval_retrieval.py`](../eval_retrieval.py) — offline, no API keys |
| **Packages** | Real OSS Python libraries: **`requests`** and **`click`** (MIT). Indexer runs on the package source tree only (not bundled tests/docs). Indexed graph size (symbols as nodes, resolved edges): **requests** ~318 nodes / 912 edges · **click** ~622 nodes / 2,426 edges (exact counts vary slightly with indexer version). |
| **Seeds** | **15 auto-selected** symbols per task: highest in-degree for `blast_radius`, highest out-degree for `dependencies` (via `--num-seeds 15`). Optional held-out cases: `--cases eval/cases/<repo>.json` (see §4.4). |
| **Tasks** | `blast_radius` (relevant = transitive **callers**; `backward_weight = 0.9`) · `dependencies` (relevant = transitive **callees**; `backward_weight = 0.3`) |
| **Headline metric** | **Precision@10** on `blast_radius`, averaged over seeds. We do **not** headline Recall@k (see §4.5). |

**Three arms** (fixed top-k budget):

1. **`brute_force`** — 1-hop neighbours only, ranked by node degree (naive structural baseline).
2. **`uni_directional`** — forward-only PPR (`backward_weight = 0.0`; ablation).
3. **`bi_directional`** — shipped engine (`get_context_ppr`) with task weights `IMPACT = 0.9` / `CONTEXT = 0.3`.

**Reproduce** (from repo root; requires a clone of each library beside the harness):

```bash
# requests (example layout: ../benchmarks/requests/src/requests)
python eval_retrieval.py --codebase-dir <path-to-requests>/src/requests \
  --task blast_radius --k "3,5,10" --num-seeds 15

# click (example layout: ../benchmarks/click/src/click)
python eval_retrieval.py --codebase-dir <path-to-click>/src/click \
  --task blast_radius --k "3,5,10" --num-seeds 15
```

Indexer notes for reproducibility: symbol rows are **deduplicated by FQN** (keeping the largest body, so `@overload` stubs do not create phantom nodes), and `contains` edges use `INSERT OR IGNORE` so real repos do not abort on duplicate containment rows.

**Mechanism check** (toy graph, not generalisable): self-index the tool's own `src/` (38 nodes / 65 edges) with `--codebase-dir src` to verify that forward-only PPR is blind to upstream callers — see §4.3.

### 4.2 Results — Precision on Real Packages (headline)

**Task: `blast_radius` · Precision@10** (15 seeds per package, post dedup; rounded to two decimals)

| Arm | `requests` | `click` | `httpx` |
|-----|------------|---------|---------|
| `uni_directional` (ablation) | 0.27 | 0.64 | 0.65 |
| **`bi_directional` (shipped)** | **0.98** | **0.99** | **0.98** |
| `brute_force` (1-hop) | 0.97 | 0.98 | 0.99 |

**Reading the table.**

- **Bidirectional PPR matches** the 1-hop brute-force baseline on precision (~0.97–0.99) while ranking over the full graph (not limited to direct neighbours).
- **Unidirectional PPR degrades sharply** (0.27 / 0.64 / 0.65 on `requests` / `click` / `httpx`): a forward-only retriever spends most of its top-k budget on **downstream** mass, not upstream callers — the empirical reason the backward pass is a **necessary** component for blast-radius mode (`get_impact`, `plan_change`), not decoration.
- We state this **without overselling multi-hop recall**: a fair multi-hop baseline (e.g. BFS-depth-k) is future work; comparing recall only on hop ≥ 2 while brute_force is 1-hop would rig the comparison.

The `dependencies` task is reported in harness output but **not headlined**: forward PPR is already strong downstream; bidirectional ties unidirectional on recall in the toy graph (§4.3) — the product differentiator is concentrated in **blast radius**.

> **Summary.** Bidirectional PPR **matches** a 1-hop structural baseline on precision while ranking over the full graph; unidirectional PPR **collapses** on blast radius because it cannot see upstream callers. That validates the backward pass as a **necessary** component for impact-analysis tasks (`get_impact`, `plan_change`).

### 4.3 Mechanism Illustration — Toy Self-Graph (Recall only)

The tables below are on GraphRAG-Code's own **`src/`** graph (38 nodes / 65 edges). They **illustrate why** `uni_directional` fails on blast radius; they are **not** headline evidence for external packages.

**`blast_radius`** (relevant = transitive callers; `backward_weight = 0.9`)

| Arm | Recall@3 | Recall@5 | Recall@10 |
|-----|----------|----------|-----------|
| `brute_force` | 0.729 | 0.751 | 0.762 |
| `uni_directional` | 0.000 | 0.000 | 0.000 |
| **`bi_directional`** | **0.840** | **0.978** | **1.000** |

**`dependencies`** (relevant = transitive callees; `backward_weight = 0.3`)

| Arm | Recall@3 | Recall@5 | Recall@10 |
|-----|----------|----------|-----------|
| `brute_force` | 0.744 | 0.759 | 0.789 |
| `uni_directional` | 0.889 | 0.959 | 1.000 |
| `bi_directional` | 0.889 | 0.959 | 1.000 |

Reproduce: `python eval_retrieval.py --codebase-dir src --task both --k "3,5,10" --num-seeds 15`.

### 4.4 Interpretation

1. **Backward pass is necessary for blast radius.** Toy graph: `uni_directional` Recall = 0.000 at every k. Real packages: Precision@10 collapses to 0.27–0.64 while bidirectional holds ~0.98. Same mechanism, two scales of evidence.
2. **Brute force is a strong but shallow baseline on precision.** It competes on Precision@10 because many relevant callers are 1-hop away; it still cannot rank multi-hop impact without expanding the neighbourhood blindly.
3. **Honest null on dependencies.** Downstream retrieval does not require a heavy backward lean; bidirectional does not harm forward-dominated queries. Value of the second direction is **task-selective** (weight 0.9 vs 0.3), matching `get_impact` vs `get_context`.
4. **Held-out cases.** Auto-seeds favour high-degree hubs. Fixed `(symbol, task)` pairs outside the top-15 auto-seed list: [`eval/cases/requests.json`](../eval/cases/requests.json), [`eval/cases/click.json`](../eval/cases/click.json), [`eval/cases/httpx.json`](../eval/cases/httpx.json) (8 cases each). On `blast_radius`, `uni_directional` still scores **0.000** recall@k on held-out seeds; `bi_directional` matches or exceeds the ablation — same mechanism as §4.2.

### 4.5 Threats to Validity & Limitations

| Threat | Implication |
|--------|-------------|
| **Package count** | Headline Precision@10 on **`requests`**, **`click`**, **`httpx`** (§4.2). Three packages show the same pattern: `uni` ≈ 0.27–0.65, `bi` ≈ 0.98–0.99. More repos strengthen generalisation (see §5). |
| **Recall@k vs closure size** | Ground truth = full transitive closure. On large graphs, a hub with hundreds of transitive callers caps Recall@10 mechanically — the metric tracks **closure size** as much as ranking quality. Hence **Precision@10** is the durable headline for blast radius. |
| **Ground truth edge mix** | Closure includes `call`, `extends`, `import`, and `contains` edges. A call-only variant is planned. |
| **Call resolution gap (vs. Codebase-Memory)** | Same limitation as [§3 — Call resolution gap](#3-trade-offs-and-limitations): Vogel et al. use a **6-strategy call-resolution cascade** (confidence 0.95→0.30), including LSP-style resolution for Go/C/C++. GraphRAG-Code uses **short_name matching** plus import heuristics. Cross-file calls via `obj.method()` (common in `requests`) may be missed or merged incorrectly — reported precision is therefore a **lower bound** under our resolver, not an upper bound. Future work: LSIF/SCIP-assisted edges (§3). |
| **Auto-seed selection** | Top-degree seeds stress-test hubs; held-out `--cases` mitigate cherry-picking concerns. |
| **No BM25 / embedding baseline yet** | Lexical retrieval may win on PL→PL completion; structural RQ1 does not subsume that task class (JetBrains 2025; see literature review). |
| **Workload-dependent graphs (literature)** | Chinthareddy (2026): DKB **ties** No-Graph on ThingsBoard (14/15). Our RQ1 measures **structural retrieval only**, not end-to-end LLM answer quality. |

### 4.6 Next Steps (RQ1 track)

1. ~~Held-out case files (`requests`, `click`, `httpx`)~~ ✅
2. ~~**`httpx`** in headline table~~ ✅
3. **BM25** chunk baseline and **BFS-depth-k** multi-hop baseline (fair comparison, not hop≥2-only recall).
4. Aggregate ≥5 repos for a preprint-grade table; until then, **§4.2 + README** are the single source of truth for headline numbers.

## 5. Evaluation Roadmap (Future Work)

RQ1 structural retrieval (§4): precision@10 on **`requests`**, **`click`**, and **`httpx`** is documented; expansion to more repos and baselines remains open.

1. **Rigor Benchmark:** Extend RQ1 (`eval_retrieval.py`) to $\ge$ 5–10 varied open-source Python repositories and aggregate (partial: **3/5+** done — see §4.2).
2. **Baselines:** (A) 1-hop brute force ✅ · (B) Unidirectional PPR ablation ✅ · (C) BM25 chunking *(pending)* · (D) BFS-depth-k multi-hop *(pending, for fair multi-hop comparison)*.
3. **Metrics:** Headline structural retrieval on **Precision@k** for blast radius; Token Savings, Latency, DRQ, and API Hallucination Rate for agent-facing studies — not CodeBLEU alone.
