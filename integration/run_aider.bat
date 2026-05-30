@echo off
echo [🚀] Activating Parasite Integration with Gemini
echo [⚡] Launching Aider and mounting GraphRAG-Code Knowledge Space...

:: Set Gemini API Key environment variable (Insert your key here or set it in your terminal)
set GEMINI_API_KEY="your-gemini-api-key"

:: Launch Aider with custom MCP config and force Gemini model
..\venv312\Scripts\aider.exe --model gemini/gemini-2.5-flash-lite --mcp .\aider_mcp_config.json
pause
