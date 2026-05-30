# Tích hợp Hệ Sinh Thái (Integration)

Thư mục này chứa các thiết lập để cắm **CodeGraph MVP** thẳng vào **Aider** (hoặc các AI coding assistants tương thích giao thức MCP như Claude Desktop, Cursor) một cách nguyên bản (Native MCP) mà không cần can thiệp mã nguồn của client.

## Các File Có Sẵn:

1. **`aider_mcp_config.json`**: File cấu hình chứa khai báo stdio transport.
2. **`run_aider.ps1`**: Script Powershell tự động khởi chạy Aider kèm với cấu hình MCP.

## Hướng dẫn sử dụng:

1. Đảm bảo bạn đã chạy `codegraph-index` để sinh ra file DB `codegraph.sqlite`.
2. Mở Terminal (Powershell), di chuyển vào thư mục `integration\`:
   ```powershell
   cd integration
   ```
3. Cấu hình API Key của Google Gemini trực tiếp trên Terminal của bạn:
   ```powershell
   $env:GEMINI_API_KEY="your-api-key"
   ```
4. Chạy script để gọi Aider (Script đã được set mặc định ép dùng model `gemini-1.5-pro-latest`):
   ```powershell
   .\run_aider.ps1
   ```
5. Aider sẽ khởi động và kết nối với MCP Server `CodeGraph`.
6. Thử gõ câu lệnh "Killer Prompt" vào Aider: 
   > *"Dùng tool list_symbols liệt kê các hàm trong file mcp_server.py"*
   
Aider sẽ tự động nhận diện các công cụ chúng ta đã trang bị (`list_symbols`, `get_callers`, `get_pruned_context`) và biến thành một trợ lý có khả năng soi chiếu mọi ngóc ngách của hệ thống!
