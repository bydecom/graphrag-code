# GraphRAG-Code - MCP Setup for Cursor / Claude

To integrate GraphRAG-Code into your development environment as an MCP Server, follow the configuration steps below.

Note: You must install GraphRAG-Code via `pip install -e .` before performing this step so the system can recognize the `graphrag-code-mcp` command.

## For Cursor IDE
1. Open Settings -> Features -> MCP Servers
2. Select "Add New MCP Server"
3. Configure it as follows:
   - Name: `GraphRAG-Code`
   - Type: `command`
   - Command: `graphrag-code-mcp`

## For Claude Desktop
Add the following JSON block to your Claude configuration file (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "GraphRAG-Code": {
      "command": "graphrag-code-mcp",
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "CODEGRAPH_DB": "graphrag_code.sqlite"
      }
    }
  }
}
```

*Note: If your database is located elsewhere, modify `CODEGRAPH_DB` to point to the absolute path of your `.sqlite` file.*
