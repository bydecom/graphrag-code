# Phase 3: Chiến dịch Ký Sinh (Parasite Integration)

Thư mục này chứa các thiết lập để cắm **CodeGraph MVP** thẳng vào **Aider** (hoặc các AI coding assistants tương thích giao thức MCP như Claude Desktop, Cursor) một cách nguyên bản (Native MCP) mà không cần can thiệp mã nguồn của client.

## Các File Có Sẵn:

1. **`aider_mcp_config.json`**: File cấu hình chứa khai báo stdio transport. File này xác định:
   - Command: Trỏ đúng vào `venv312` để chạy Python.
   - Env: Bật cờ UTF-8 và trỏ đường dẫn tới `codegraph.sqlite`.
2. **`run_aider.ps1`**: Script Powershell tự động khởi chạy Aider kèm với cờ `--mcp`.

## Hướng dẫn sử dụng:

1. Đảm bảo bạn đã chạy `indexer.py` để sinh ra file DB `codegraph.sqlite` (cập nhật mới nhất).
2. Mở Terminal (Powershell), di chuyển vào thư mục `integration\`:
   ```powershell
   cd d:\Workspace\Project\codebase_knowledge_graph\codegraph_mvp\integration
   ```
3. Cấu hình API Key của Google Gemini trực tiếp trên Terminal của bạn:
   ```powershell
   $env:GEMINI_API_KEY="điền_key_bắt_đầu_bằng_AIzaSy_của_bạn_vào_đây"
   ```
4. Chạy script để gọi Aider (Script đã được set mặc định ép dùng model `gemini-1.5-pro-latest`):
   ```powershell
   .\run_aider.ps1
   ```
5. Aider sẽ khởi động và thông báo đã kết nối thành công với MCP Server `CodeGraph_Enterprise_V1`.
6. Thử gõ câu lệnh "Killer Prompt" vào Aider: 
   > *"Dùng tool list_symbols liệt kê các hàm trong file bay_menu.py"*
   
Aider sẽ tự động nhận diện 3 vũ khí chúng ta đã trang bị (`list_symbols`, `get_callers`, `get_pruned_context`) và biến thành một "Thần Nhãn" có khả năng soi chiếu mọi ngóc ngách của hệ thống!
