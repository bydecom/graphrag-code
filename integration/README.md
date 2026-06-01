# Integration Guide

This directory contains integration configuration files and helper scripts to plug **GraphRAG-Code** directly into **Aider** (or other MCP-compliant assistants like Claude Desktop, Cursor) natively without modifying the client source code.

## Available Files:

1. **`aider_mcp_config.json`**: MCP configuration mapping stdio transport.
2. **`run_aider.ps1`**: Powershell script to easily launch Aider pre-configured with the MCP server flags.

## Usage Instructions:

1. Ensure you have run the indexer once to generate the local database file `graphrag_code.sqlite`:
   ```bash
   graphrag-code-index --db graphrag_code.sqlite src
   ```
2. Navigate to the `integration/` directory:
   ```powershell
   cd integration
   ```
3. Set your Google Gemini API Key on the terminal:
   ```powershell
   $env:GEMINI_API_KEY="your-gemini-api-key"
   ```
4. Run the script to launch Aider:
   ```powershell
   .\run_aider.ps1
   ```
5. Aider will boot and display a connection success message to the `GraphRAG-Code` MCP Server.
6. Test it out with a query:
   > *"Use the tool list_symbols to list functions in mcp_server.py"*

Aider will dynamically register all exposed MCP tools — `list_symbols`, `get_callers`, `get_pruned_context`, `get_impact` (blast-radius ranking), and `get_context` (360° caller + source + dependency view) — and act as an intelligent coding assistant with precise, context-aware retrieval.
