# Research Positioning & Limitations

This document serves as the academic positioning and a critical evaluation of the CodeGraph prototype. It outlines the specific research questions addressed, contextualizes our approach against current state-of-the-art literature, and candidly discusses the system's limitations.

## 1. Research Question & Problem Statement

**Problem:** Standard Code RAG relying solely on vector similarity (e.g., embeddings) struggles with *structural queries* (e.g., "What is the blast radius of modifying function X?" or "Find all functions that call Y"). Sending the entire codebase to an LLM context window is cost-prohibitive and can induce hallucination or defensive over-engineering.

**Question:** Can we deterministically extract a precise, token-efficient, and structurally coherent implementation context using an AST-derived graph combined with Bidirectional Personalized PageRank, without incurring the high indexing costs of LLM-generated graphs?

## 2. Academic Positioning

In the current landscape of Agentic Graph-RAG (2025-2026), CodeGraph is positioned as an **engineering extension** of two prominent research lines:

1. **Aider's Repo Map (2024):** Aider uses standard PageRank over a Tree-Sitter AST graph. However, standard PageRank measures *global popularity* (e.g., a utility function will always score high), which may not capture task-specific relevance. CodeGraph applies **Personalized PageRank (PPR)** where energy propagates outwards from the *active seed node*, ranking files based on relevance to the specific task rather than global popularity.
2. **Reliable Graph-RAG (2026):** Recent studies show AST-derived graphs (Deterministic Knowledge Bases) outperforming LLM-extracted knowledge graphs in accuracy and cost. CodeGraph aligns with this finding and implements **Bidirectional Traversal Merge**. By merging Forward PPR (downstream dependencies) with Backward PPR evaluated on a reversed graph (upstream callers/impact), the system balances the extraction of *implementation details* and *blast radius* within a single query.

*Positioning Statement:* CodeGraph extends the Aider RepoMap and Codebase-Memory paradigms by merging bidirectional Personalized PageRank scores, extracting exact source code blocks in $O(1)$ disk I/O, and exposing the graph to IDE agents via standard Model Context Protocol (MCP) tools.

## 3. Trade-offs and Limitations

To transition from a "solid engineering prototype" to a novel academic contribution, several limitations must be acknowledged and addressed in future iterations:

- **Syntax vs. Semantics:** Tree-sitter provides syntax-level parsing. Without deep static analysis (like LSIF or SCIP), relationships such as `obj.method()` cannot be deterministically resolved if `obj`'s type is unknown. Decorators, metaclasses, and dynamic imports represent blind spots in the graph.
- **Accuracy vs. Efficiency Trade-off:** While the graph approach saves ~90% token consumption compared to brute-force file reading, studies (like Codebase-Memory) suggest that Graph-based extraction can sometimes lower overall answer accuracy (e.g., 83% vs 92%). CodeGraph has not yet run rigorous evaluations on when this accuracy drop occurs.
- **Hyperparameter Dependency:** The `backward_weight` parameter (currently set to 0.7) is a heuristic. A proper ablation study is needed to find the optimal balance between forward and backward context propagation.
- **Need for Hybrid Search:** Graph RAG dominates structural queries, but BM25 or Dense Vector search is still superior for simple PL$\rightarrow$PL code completion tasks. A future intent router is required.

## 4. Evaluation Roadmap (Future Work)

To validate the academic efficacy of CodeGraph, the following benchmarks must be conducted:
1. **Rigor Benchmark:** Run on $\ge$ 10 varied open-source repositories.
2. **Baselines:** Compare against (A) Full-file brute force, (B) Unidirectional PPR, and (C) BM25 chunking.
3. **Metrics:** Measure Token Savings, Latency, and custom structural metrics such as Dependency Resolution Quality (DRQ) and API Hallucination Rate, rather than generic metrics like CodeBLEU.
