# Script khởi động Aider (Parasite Integration)
# Chạy script này từ thư mục codegraph_mvp\integration

Write-Host "[🚀] Kích hoạt 'Chiến dịch Ký Sinh' (Parasite Integration) với Gemini" -ForegroundColor Green
Write-Host "[⚡] Khởi động Aider và cắm Không gian Tri thức CodeGraph..." -ForegroundColor Yellow

# Bật biến môi trường API Key cho Gemini (Nhập key thật của bạn ở Terminal hoặc bỏ comment dòng dưới)
# $env:GEMINI_API_KEY="AIzaSy...nhập_key_vào_đây..."

# Trỏ Aider tới file config JSON để spawn CodeGraph MCP Server, đồng thời ép dùng Gemini
..\venv312\Scripts\aider.exe --model gemini/gemini-2.5-flash-lite --mcp .\aider_mcp_config.json
