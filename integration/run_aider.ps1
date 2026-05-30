# Script to launch Aider with GraphRAG-Code MCP Server
# Run this script from the graphrag-code\integration directory

Write-Host "[🚀] Activating Parasite Integration with Gemini" -ForegroundColor Green
Write-Host "[⚡] Launching Aider and mounting GraphRAG-Code Knowledge Space..." -ForegroundColor Yellow

# Set Gemini API Key environment variable (Insert your key here or set it in your terminal)
# $env:GEMINI_API_KEY="your-gemini-api-key"

# Launch Aider with custom MCP config and force Gemini model
..\venv312\Scripts\aider.exe --model gemini/gemini-2.5-flash-lite --mcp .\aider_mcp_config.json
