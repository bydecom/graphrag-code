@echo off
echo [🚀] Kich hoat 'Chien dich Ky Sinh' (Parasite Integration) voi Gemini
echo [⚡] Khoi dong Aider va cam Khong gian Tri thuc GraphRAG-Code...

:: Bật biến môi trường API Key cho Gemini (Nhập key thật của bạn ở Terminal hoặc bỏ comment dòng dưới)
set GEMINI_API_KEY="REVOKED_GEMINI_KEY"

:: Trỏ Aider tới file config JSON để spawn GraphRAG-Code MCP Server, đồng thời ép dùng Gemini
..\venv312\Scripts\aider.exe --model gemini/gemini-2.5-flash-lite --mcp .\aider_mcp_config.json
pause
