# GraphRAG-Code 🚀
**Python-native Code Knowledge Graph using bidirectional Personalized PageRank**

*A directed-graph PPR engine that ranks structurally related code and extracts exact source blocks (not just metadata). A single tunable weight selects between two query modes: downstream dependency context and upstream blast-radius.*

**Author:** [Bydecom](https://github.com/bydecom) · [graphrag-code](https://github.com/bydecom/graphrag-code)

## Why GraphRAG-Code? (The "Why")

In 2026, dumping entire raw files into LLM Agents is highly inefficient, leading to high token costs and increased hallucination rates.  
GraphRAG-Code solves this by combining **Abstract Syntax Tree (AST)** parsing with **Personalized PageRank run in both edge directions** (forward on the graph, backward on a reversed graph) on an optimized, in-memory graph. The two passes are merged with a tunable `backward_weight`.

```mermaid
graph TD
    Source[Source Code] -->|"Tree-sitter AST"| Indexer[SQLite DB]
    Indexer -->|"In-Memory Load"| Engine[rustworkx Graph]
    Engine -->|"Bidirectional PPR"| MCP[FastMCP Server]
    MCP -->|"stdio Protocol"| Client[Cursor Agent]
```

## 📊 Benchmark Status (honest)

Older, small-codebase numbers are **not** used as headline evidence anymore. The current, reproducible benchmark story is **RQ1** below (LLM-free structural retrieval), with full methodology + threats-to-validity in [`docs/RESEARCH.md`](docs/RESEARCH.md).

### 🧪 RQ1 — Structural Retrieval (deterministic, no LLM)

A reproducible, LLM-free retrieval eval ([`eval_retrieval.py`](eval_retrieval.py)) compares three arms against a graph-derived ground truth (transitive closure). The durable, repo-independent finding is on **precision** for blast-radius queries: a forward-only PageRank spends most of its budget on irrelevant nodes, while Bidirectional PPR stays sharp — empirical evidence that the backward pass is a **necessary** component, not decoration.

| `blast_radius` · Precision@10 | `requests` | `click` | `httpx` |
|-------------------------------|-----------|---------|---------|
| Unidirectional PPR (ablation) | 0.27 | 0.64 | 0.65 |
| **Bidirectional PPR (ours)** | **0.98** | **0.99** | **0.98** |
| Brute-force (1-hop) | 0.97 | 0.98 | 0.99 |

> Measured on the real `requests`, `click`, and `httpx` packages (15 auto-seeds each, post symbol-dedup). Held-out case files (outside top-15 seeds): [`eval/cases/`](eval/cases/). Bidirectional **matches** a naive 1-hop baseline on precision and **far exceeds** the single-direction ablation. We deliberately do **not** headline Recall@k: against a full transitive-closure ground truth it is dominated by closure size on large graphs. Reproduce: `python eval_retrieval.py --codebase-dir <pkg> --task blast_radius --k "3,5,10"`. Full methodology: [`docs/RESEARCH.md` §4](docs/RESEARCH.md).

### Install (PyPI)

```bash
pip install graphrag-code-core
graphrag-code-index --db graphrag_code.sqlite src
graphrag-code-mcp   # MCP stdio server (configure in Cursor / Claude Desktop)
```

Package name on PyPI is **`graphrag-code-core`** (repo: [graphrag-code](https://github.com/bydecom/graphrag-code)).

### 🔥 Core Differentiators:
- **Bidirectional PPR Merge (two query modes):** An engineering extension of the Repo Map concept. It runs Forward PPR (downstream dependencies) and Backward PPR (on the reversed graph) as two independent passes, then merges them with a tunable `backward_weight`. The default `0.2` leans toward downstream implementation context, while `get_impact` raises it to `0.9` to surface upstream callers (blast radius). It is therefore **two weight-selected modes**, not one symmetric "see everything" query.
- **Source Code Block Extraction:** Injects exact code blocks (snippets) into the LLM context using AST coordinates rather than just spitting out symbol metadata.
- **Interface Expansion (P0-2):** Traversing interface boundaries automatically via inheritance/dependency mapping (e.g., tracking consumers of implemented classes).
- **Orphan / Dead-Code Detection:** Because edges are derived purely from real `import`, `call`, `contains`, and `handles` (route→handler) relationships, modules and classes that nothing references stay disconnected from the main graph. A class that floats alone is the graph honestly telling you it is never imported or instantiated anywhere — a free static smell-detector for dead or dynamically-invoked code.
- **Route Semantic Edges:** Flask/FastAPI-style decorators (`@app.route`, `@app.get`, …) become first-class **route nodes** linked to their handler via `handles` edges — visible in the graph export as purple diamonds (e.g. `route:/users` → `get_users`).
- **Python-Native:** Highly optimized for the Python ecosystem (FastAPI, Django, Data Science).
- **Zero-Ops MCP Server:** Complies with the Model Context Protocol (MCP). Plugs directly into **Cursor** or **Claude Desktop** in seconds.

---

## 🛠 Quick Start

To run the pipeline natively using Python 3.10+:

```bash
# Install: PyPI (`pip install graphrag-code-core`) or from source (`pip install -e .`)

# Parse the codebase and generate the Knowledge Graph
graphrag-code-index --db graphrag_code.sqlite src

# Set your LLM API Key (Gemini recommended)
export GEMINI_API_KEY="your-api-key"

# Launch the interactive Terminal Agent
graphrag-code-agent
```

---

## 📊 Native IDE Integration
If you use **Cursor IDE** or **Claude Desktop**, GraphRAG-Code exposes standard Model Context Protocol (MCP) tools out-of-the-box.  
👉 See detailed instructions in [docs/CURSOR_CLAUDE_INTEGRATION.md](docs/CURSOR_CLAUDE_INTEGRATION.md).

### 🧰 MCP Tools

| Tool | When to use |
|------|-------------|
| **`plan_change`** *(v0.1.x)* | **Call before editing a symbol.** One-shot, token-light pre-edit briefing: overall risk + direct callers + ranked upstream blast radius + downstream deps. Metadata-only by default (`include_snippets=False`). |
| `get_impact` | Full blast-radius table (Bidirectional PPR, `backward_weight=0.9`) with per-row HIGH/MEDIUM/LOW confidence tiers. |
| `get_context` | 360° view of one symbol: direct callers + source code + downstream dependencies (with snippets). |
| `get_pruned_context` | Broad downstream context across related symbols, with token budgeting. |
| `get_callers` | Flat depth-1 list of upstream callers. |
| `list_symbols` | Structural overview of the codebase (or a single file). |

> Ambiguous names (e.g. a `validate` defined in two files) return a disambiguation prompt listing fully-qualified names instead of silently picking one — so blast-radius answers and benchmark seeds stay correct.

---

## 🏗 Architecture
The system utilizes `tree-sitter` to parse Python files into a graph of syntax nodes, stores it incrementally using SQLite, and loads it into a high-performance in-memory C-backed graph (`rustworkx`) to run PPR calculations in milliseconds.

---

## 🔍 Codebase Graph Visualization (Phase 2)

<p align="center">
  <img src="docs/assets/visualizer.png" alt="Codebase Knowledge Graph Visualizer" width="800"/>
</p>

> 💡 **Reading the graph:** Every symbol is attached to its file via `contains` edges, so each module forms a tight cluster of its classes and functions. If a whole cluster floats away from the rest (like an unused dialog), that is **intended** — it means nothing in the codebase statically imports or calls it. The graph surfaces orphan/dead code instead of hiding it behind fake links.

**Color Legend (Node Types):**
- 🟢 **Green (Ellipse):** `File / Module` (e.g., `main.py`)
- 🔵 **Blue (Box):** `Class` (e.g., `FullScreenApp`, `AppMenu`)
- 🟣 **Purple (Diamond):** `HTTP Route` (e.g., `route:/users`, `GET /items`) — Flask/FastAPI decorators
- ⚫ **Dark Grey (Box):** `Function / Method` (e.g., `__init__`, `create_widgets`)

**How to generate and view this interactive graph locally:**
```bash
# Export the indexed SQLite graph to a JSON format
graphrag-code-export --db graphrag_code.sqlite --out graph_data.json

# Open the visualizer in your browser and upload the JSON file
open examples/graph_visualizer.html
```

---

## Related Work

GraphRAG-Code targets **structural context for coding agents** (call/import graphs, blast radius, dependency snippets via MCP). It is **not** the [Microsoft GraphRAG](https://github.com/microsoft/graphrag) project, which indexes **unstructured text** with a different graph and query stack.

Work directly relevant to this problem:

| Reference | Relevance to GraphRAG-Code |
|-----------|----------------------------|
| [LocAgent](https://arxiv.org/abs/2503.09089) (Chen et al., ACL 2025) | Graph-guided **code localization** (where to edit) using directed heterogeneous graphs. Reports up to **92.7% file-level Acc@5** (Qwen2.5-32B-ft) with ~86% cost reduction. |
| [CodexGraph](https://arxiv.org/abs/2408.03910) (Liu et al., NAACL 2025) | Graph database (Neo4j) + Cypher queries as the interface between agents and repositories; evaluated on CrossCodeEval, SWE-bench, and EvoCodeBench. |
| [RepoGraph](https://arxiv.org/abs/2410.14684) (Ouyang et al., ICLR 2025) | Plug-in repository-level code graph module that boosts SWE-bench performance when integrated into existing frameworks (e.g., Agentless, SWE-agent). |
| [Aider Repo Map](https://aider.chat/docs/repomap.html) (Gauthier, 2024) | Tree-sitter + PageRank for repo context; we use **directed** graphs, **Personalized** PageRank from a seed symbol, and MCP-delivered **source blocks**. |
| [Codebase-Memory](https://arxiv.org/abs/2603.27277) (Vogel et al., 2026) | Tree-sitter knowledge graph + **MCP**; closest parallel. Aggregate quality 0.83 vs explorer 0.92, but graph wins hub/caller tasks on **19/31** langs. We add **Personalized** PPR and snippet extraction; they add **6-strategy call resolution**. |
| [Reliable Graph-RAG for Codebases](https://arxiv.org/abs/2601.08773) (Chinthareddy, 2026) | AST-derived DKB vs LLM-KB vs No-Graph on Java repos (Shopizer, ThingsBoard, OpenMRS). **95.6% aggregate** for DKB, but **ties** No-Graph on ThingsBoard; validates bidirectional + interface expansion. |
| *Practical Code RAG at Scale* (Galimzyanov et al., NeurIPS 2025) | Retrieval quality depends on **task type**; motivates separate tools (`get_impact` vs `get_context`) and a future hybrid intent router (graph vs lexical). |

Deeper positioning, debates, and metrics: [`docs/RESEARCH.md`](docs/RESEARCH.md) · [`docs/LITERATURE_REVIEW.md`](docs/LITERATURE_REVIEW.md).

**Sibling project:** [Medical Citation Agent](https://github.com/bydecom/medical-citation-agent) — same Deterministic-First + MCP pattern applied to FDA drug-label claim extraction with verifiable citations.

---

## Acknowledgments

Developed primarily in [Cursor](https://cursor.com). Architecture, evaluation design (`eval_retrieval.py`), and shipped code are the author's responsibility.

---

## ⚠️ Handled vs Open Limitations

GraphRAG-Code uses **assignment-based heuristics**, not a full type checker. That is intentional — full resolution is what LSP/LSIF is for (planned Phase 2). What we handle today vs what we honestly do not:

### ✅ Handled today (static AST heuristics)

| Capability | Example | How |
|------------|---------|-----|
| **Assignment-based call disambiguation** | `session = Session(); session.send()` | Maps variable → constructor class per scope; edge targets `Session.send` instead of every `send` in the repo |
| **`self` / `cls` method calls** | `self.validate()` inside `class Session` | Resolves to `Session.validate` via enclosing class context |
| **Flask / FastAPI route decorators** | `@app.route("/users")`, `@app.get("/items")` | Creates route nodes (`route:/users`, `GET /items`) with `handles` → handler function |
| **Structural edges** | `import`, `call`, `extends`, `contains` | Tree-sitter capture + cross-file import gate in `resolved_edges` |
| **Ambiguous symbol safety** | Two `validate()` in different files | MCP tools return a disambiguation list instead of silently guessing |

### ❌ Not handled (falls back to bare method name or no edge)

| Gap | Example | Why |
|-----|---------|-----|
| **`self.attr` chains** | `self.adapter.send()` after `self.adapter = HTTPAdapter()` in `__init__` | No instance-attribute type map yet |
| **Import aliases** | `from requests import Session as S; s = S(); s.send()` | Constructor tracked as `S`, not resolved to `Session` |
| **Chained call return types** | `client.get_session().send()` | Needs return-type inference |
| **Conditional / multi-path assignment** | `if x: s = A() else: s = B()` | Needs flow analysis |
| **Untyped parameters** | `def process(session): session.send()` | Needs annotations or call-site analysis |
| **Tuple/list unpacking** | `session, _ = Session(), Adapter()` | Assignment LHS not a simple identifier |
| **Dynamic dispatch** | `getattr(obj, "send")()`, `__getattr__`, metaclasses | Runtime-only; out of scope for syntax-level indexing |
| **Generic decorators** | `@login_required`, `@cache`, custom wrappers | Only HTTP route patterns are recognized |

### Other known limits

- **Python-only** for now (multi-language planned).
- **~20–25% latency overhead** on tiny codebases (<20 files) from MCP init + in-memory graph load; pays off on larger repos.
- **Private-method heuristics** (`_` prefix) are still being refined.
