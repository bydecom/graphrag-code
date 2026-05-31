import asyncio
import sys
import os
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import litellm

async def run_cli_agent():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[!] Error: Please set the GEMINI_API_KEY environment variable before running.")
        print("    In CMD: set GEMINI_API_KEY=AIzaSy...")
        print("    In Powershell: $env:GEMINI_API_KEY=\"AIzaSy...\"")
        return
        
    print("[🤖 GraphRAG-Code Agent] Booting up 'The People's Agent'...")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["CODEGRAPH_DB"] = "graphrag_code.sqlite"

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
                        "2. For deep analysis of ONE symbol: use 'get_context' (360° view: callers + source + deps in one call).\n"
                        "3. Before editing anything: call 'get_impact' to see blast radius with confidence scores.\n"
                        "4. For broad context across multiple related symbols: use 'get_pruned_context'.\n"
                        "Never edit code without first checking get_impact. Never guess dependencies."
                    )
                }
            ]
            
            print("="*60)
            print("🚀 WELCOME TO GRAPHRAG-CODE CLI AGENT (Powered by Gemini) 🚀")
            print("="*60)
            print(" Type 'exit' or 'q' to quit. Start chatting with the Agent about your project.\n")
            
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
