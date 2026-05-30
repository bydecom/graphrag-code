# CodeGraph Enterprise - MCP Setup cho Cursor / Claude

Để tích hợp CodeGraph vào môi trường phát triển của bạn dưới dạng một MCP Server, hãy cấu hình theo hướng dẫn sau.

Lưu ý: Bạn phải cài đặt CodeGraph thông qua `pip install -e .` trước khi thực hiện bước này để hệ thống nhận diện được lệnh `codegraph-mcp`.

## Dành cho Cursor IDE
1. Mở Cài đặt (Settings) -> Features -> MCP Servers
2. Chọn "Add New MCP Server"
3. Thiết lập như sau:
   - Name: `CodeGraph`
   - Type: `command`
   - Command: `codegraph-mcp`

## Dành cho Claude Desktop
Thêm đoạn JSON sau vào file cấu hình của Claude (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "CodeGraph": {
      "command": "codegraph-mcp",
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "CODEGRAPH_DB": "codegraph.sqlite"
      }
    }
  }
}
```

*Lưu ý: Nếu bạn để database ở vị trí khác, hãy sửa `CODEGRAPH_DB` trỏ tới đường dẫn tuyệt đối của file `.sqlite` đó.*
