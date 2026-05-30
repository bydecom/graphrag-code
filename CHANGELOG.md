# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-05-31
### Added
- **Core Engine**: `GraphRAG-CodeEngine` featuring a Bidirectional Personalized PageRank (B-PPR) algorithm to achieve up to 91% token savings.
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
