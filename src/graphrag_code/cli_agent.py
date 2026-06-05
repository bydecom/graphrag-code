import asyncio
import sys
import os
import json
import sqlite3
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import litellm
from dotenv import load_dotenv

def _describe_indexed_graph(db_path: str) -> str:
    """Human-readable summary of what is loaded — shown at startup for transparency."""
    if not os.path.exists(db_path):
        return f"[!] No index at `{db_path}` — run the indexer first."
    conn = sqlite3.connect(db_path)
    file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    sym_count = conn.execute("SELECT COUNT(*) FROM symbols WHERE kind != 'module'").fetchone()[0]
    edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    sample_paths = [row[0] for row in conn.execute("SELECT file_path FROM files LIMIT 3").fetchall()]
    conn.close()

    # Infer codebase label from indexed paths (e.g. .../click/src/click/core.py → click)
    codebase = "unknown"
    for path in sample_paths:
        parts = path.replace("\\", "/").split("/")
        for i, part in enumerate(parts):
            if part == "src" and i + 1 < len(parts):
                codebase = parts[i + 1]
                break
        if codebase != "unknown":
            break

    lines = [
        f"  DB:        {os.path.abspath(db_path)}",
        f"  Codebase:  {codebase} ({file_count} files, {sym_count} symbols, {edge_count} edges)",
    ]
    if sample_paths:
        lines.append(f"  Sample:    {os.path.basename(sample_paths[0])} …")
    return "\n".join(lines)

def _preview_tool_result(text: str, max_lines: int = 18) -> str:
    """Truncate tool output for terminal display (screenshot-friendly)."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines]) + f"\n  … ({len(lines) - max_lines} more lines)"

async def run_cli_agent():
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[!] Error: GEMINI_API_KEY not found.")
        print("    Add it to .env in the graphrag-code folder (see .env.example).")
        return
        
    print("[🤖 GraphRAG-Code Agent] Booting up 'The People's Agent'...")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    db_path = os.environ.get("GRAPHRAG_CODE_DB") or os.environ.get("CODEGRAPH_DB", "graphrag_code.sqlite")
    env["GRAPHRAG_CODE_DB"] = db_path

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "graphrag_code.mcp_server"],
        env=env
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("[🤖 GraphRAG-Code Agent] Successfully connected to MCP Server!")
            
            # 1. Automatically extract Schema from MCP Server
            mcp_tools = await session.list_tools()
            llm_tools = []
            for t in mcp_tools.tools:
                llm_tools.append({
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.inputSchema
                    }
                })
                
            messages = [
                {
                    "role": "system", 
                    "content": (
                        "You are a world-class AI Software Architect working on a large codebase.\n"
                        "Mandatory procedure before analyzing or modifying code:\n"
                        "1. ALWAYS call 'list_symbols' first for a structural overview.\n"
                        "2. Before editing ANY symbol: call 'plan_change' first — it gives a single, token-light\n"
                        "   pre-edit briefing (overall risk + ranked upstream blast radius + downstream deps).\n"
                        "3. For deep analysis / to read actual code: use 'get_context' (360° view: callers + source + deps).\n"
                        "4. For the full blast-radius table only: use 'get_impact'.\n"
                        "5. For broad context across multiple related symbols: use 'get_pruned_context'.\n"
                        "Never edit code without first calling plan_change. Never guess dependencies.\n"
                        "If asked what codebase you are on, you MUST call list_symbols and cite real\n"
                        "file paths from the tool result — never answer from general knowledge."
                    )
                }
            ]
            
            print("="*60)
            print("🚀 WELCOME TO GRAPHRAG-CODE CLI AGENT (Powered by Gemini) 🚀")
            print("="*60)
            print("[📂 Indexed Graph]")
            print(_describe_indexed_graph(db_path))
            print()
            print(" Screenshot demo prompts (copy-paste):")
            print("  1) Gọi plan_change cho Command.invoke — blast radius trước khi sửa")
            print("  2) Gọi list_symbols file_path core.py — liệt kê class/function")
            print("  3) Nếu sửa invoke, dùng get_impact để xem ai bị ảnh hưởng")
            print()
            print(" Type 'exit' or 'q' to quit.\n")
            
            while True:
                try:
                    user_input = input("[👨‍💻 You]: ")
                    if user_input.strip().lower() in ['quit', 'exit', 'q']:
                        break
                    if not user_input.strip(): continue
                    
                    messages.append({"role": "user", "content": user_input})
                    
                    # Agent Loop (Handling Tool Calling Chain of Thought)
                    while True:
                        print(" [⏳ Agent is thinking...]", end="\r")
                        response = await litellm.acompletion(
                            model="gemini/gemini-2.5-flash-lite",
                            messages=messages,
                            tools=llm_tools,
                            api_key=api_key
                        )
                        
                        msg = response.choices[0].message
                        # Remove empty fields to avoid strict LLM format errors
                        msg_dict = msg.model_dump(exclude_none=True)
                        messages.append(msg_dict)
                        
                        if msg.tool_calls:
                            print(" "*50, end="\r") # Clear waiting line
                            for tool_call in msg.tool_calls:
                                func_name = tool_call.function.name
                                args = json.loads(tool_call.function.arguments)
                                print(f"  [🔧 TOOL EXECUTION]: Running `{func_name}` with args: {args}")
                                
                                # Communicate via the real MCP protocol down to the Graph Engine
                                tool_result = await session.call_tool(func_name, arguments=args)
                                result_text = "\n".join([c.text for c in tool_result.content if c.type == "text"])
                                preview = _preview_tool_result(result_text)
                                if preview.strip():
                                    print(f"  [📊 Graph Result]:\n{preview}\n")
                                
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": func_name,
                                    "content": result_text
                                })
                            # Loop back to report to Gemini after Tools finish executing
                        else:
                            # If no tools called, print text response
                            print(" "*50, end="\r") 
                            print(f"\n[🤖 Agent]:\n{msg.content}\n")
                            break
                            
                except KeyboardInterrupt:
                    print("\n[👋] See you later!")
                    break
                except Exception as e:
                    print(f"\n[!] Fatal error: {str(e)}")
                    break

def main():
    # Suppress debug info for clean terminal UI
    litellm.suppress_debug_info = True 
    # Fix async event loop execution on Windows
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_cli_agent())

if __name__ == "__main__":
    main()
