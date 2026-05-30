# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-05-31
### Added
- **Core Engine**: `CodeGraphEngine` với thuật toán Bidirectional Personalized PageRank (B-PPR) để cắt tỉa (pruning) AST tokens lên đến 91%.
- **Indexer**: Hỗ trợ Incremental Parsing mã nguồn Python thông qua `tree-sitter` và SQLite MD5 Checksums.
- **MCP Server**: Triển khai giao thức Model Context Protocol (`codegraph-mcp`) tương thích Cursor, Claude Desktop, Aider.
- **CLI Agent**: Cung cấp `codegraph-agent` để chat trực tiếp với codebase.
- **Benchmark Suite**: Script đánh giá thực tế token savings, latency và accuracy.

### Changed
- Cấu trúc lại dự án tuân theo tiêu chuẩn Packaging (PIP package `codegraph-core`).

### Fixed
- Lỗi vòng lặp vô tận (Infinite recursive logic) khi gọi các hàm cross-file.
- Tự động bỏ qua các build-in functions (`print`, `len`...) để tránh nhiễu đồ thị.
- Tràn RAM khi export đồ thị lớn nhờ streaming SQLite cursor thay vì fetchall.
- **[CRITICAL]** Fix tương thích API `captures()` của `tree-sitter` v0.23+ thông qua class `QueryCursor`.
- Tự động resolve đường dẫn tuyệt đối (Absolute Path) trong `graph_engine.py` giúp trích xuất mã nguồn ổn định khi chạy MCP qua Cursor/Aider.
