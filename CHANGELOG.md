# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
### Added
- **Fully Qualified Names (FQN)**: Symbols are now stored with module-prefixed FQNs to disambiguate same-named symbols across files.
- **`get_impact` & `get_context` MCP tools**: Blast-radius ranking (PPR confidence tiers) and a 360° context view.
- **Extended test suite** (`tests/test_graph_engine_extended.py`): node resolution, PPR return semantics, backward-weight behaviour, source extraction, and graph-structure invariants.

### Changed
- **Single source of truth for merge weights**: `backward_weight` presets (`DEFAULT`/`CONTEXT`/`IMPACT`) and the merge-mode threshold now live as named constants in `graph_engine.py`.
- **Honest algorithm framing**: Documentation now describes the engine as two independent PPR passes merged by a tunable weight (two query modes), and cites Lofgren et al. (2016) only as *conceptual inspiration*, not as the implemented algorithm.
- **Environment variable renamed** `CODEGRAPH_DB` → `GRAPHRAG_CODE_DB` (legacy name still honoured as a fallback).

### Fixed
- Consistent imports in `ablation_runner.py` so it runs from the repo root regardless of install state.

## [0.1.0] - 2026-05-31
### Added
- **Core Engine**: `GraphRAG-CodeEngine` featuring bidirectional Personalized PageRank (forward + reversed-graph passes merged by weight) achieving up to ~97% token savings on structural queries (see `docs/RESEARCH.md`).
- **Indexer**: Incremental static parsing of Python codebase via `tree-sitter` and SQLite MD5 checksum tracking.
- **MCP Server**: Implemented Anthropic's Model Context Protocol (`graphrag-code-mcp`) compatible with Cursor, Claude Desktop, and Aider.
- **CLI Agent**: Out-of-the-box terminal interface (`graphrag-code-agent`) to chat directly with your codebase.
- **Benchmark Suite**: Quantitative evaluation script assessing token savings, latency, and retrieval accuracy.

### Changed
- Refactored the core project structure into a clean, packageable format (`graphrag-code-core`).

### Fixed
- Resolved infinite recursion loops when traversing deep cross-file dependencies.
- Automatically bypassed built-in utility functions (`print`, `len` etc.) to minimize graph noise.
- Fixed RAM exhaustion during large-scale graph exports via SQLite streaming cursors.
- **[CRITICAL]** Resolved compilation and query issues with `tree-sitter>=0.23` APIs by migrating to `QueryCursor`.
- Implemented **Dynamic Path Resolution** in `graph_engine.py` to fix the "Source file not found" error during IDE-hosted MCP execution.
