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
        print("[!] Lỗi: Hãy set biến môi trường GEMINI_API_KEY trước khi chạy.")
        print("    Trong CMD: set GEMINI_API_KEY=AIzaSy...")
        print("    Trong Powershell: $env:GEMINI_API_KEY=\"AIzaSy...\"")
        return
        
    print("[🤖 CodeGraph Agent] Đang khởi động 'The People's Agent'...")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["CODEGRAPH_DB"] = "codegraph.sqlite"

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "codegraph.mcp_server"],
        env=env
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("[🤖 CodeGraph Agent] Đã kết nối MCP Server thành công!")
            
            # 1. Trích xuất Schema tự động từ MCP Server
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
                    "content": "Bạn là AI Software Architect đẳng cấp. Đang làm việc với một repo codebase lớn.\n"
                               "Quy trình bắt buộc trước khi code/phân tích:\n"
                               "1. LUÔN dùng 'list_symbols' để xem tổng quan file/module.\n"
                               "2. LUÔN dùng 'get_callers' để đánh giá Bán Kính Sát Thương (Blast Radius).\n"
                               "3. LUÔN dùng 'get_pruned_context' để đọc mã nguồn chính xác nhất."
                }
            ]
            
            print("="*60)
            print("🚀 CHÀO MỪNG TỚI CODEGRAPH CLI AGENT (Powered by Gemini) 🚀")
            print("="*60)
            print(" Gõ 'exit' hoặc 'q' để thoát. Bắt đầu chat với Agent về dự án của bạn.\n")
            
            while True:
                try:
                    user_input = input("[👨‍💻 Bạn]: ")
                    if user_input.strip().lower() in ['quit', 'exit', 'q']:
                        break
                    if not user_input.strip(): continue
                    
                    messages.append({"role": "user", "content": user_input})
                    
                    # Agent Loop (Xử lý Tool Calling Chain of Thought)
                    while True:
                        print(" [⏳ Agent đang suy nghĩ...]", end="\r")
                        response = await litellm.acompletion(
                            model="gemini/gemini-2.5-flash-lite",
                            messages=messages,
                            tools=llm_tools,
                            api_key=api_key
                        )
                        
                        msg = response.choices[0].message
                        # Xoá trường trống để tránh lỗi strict format của LLM
                        msg_dict = msg.model_dump(exclude_none=True)
                        messages.append(msg_dict)
                        
                        if msg.tool_calls:
                            print(" "*50, end="\r") # Xóa dòng waiting
                            for tool_call in msg.tool_calls:
                                func_name = tool_call.function.name
                                args = json.loads(tool_call.function.arguments)
                                print(f"  [🔧 CẤP QUYỀN TOOL]: Đang thực thi `{func_name}` với tham số: {args}")
                                
                                # Giao tiếp qua giao thức MCP thực sự xuống Não Đồ Thị
                                tool_result = await session.call_tool(func_name, arguments=args)
                                result_text = "\n".join([c.text for c in tool_result.content if c.type == "text"])
                                
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": func_name,
                                    "content": result_text
                                })
                            # Sau khi Tools chạy xong, tự động quay lại vòng lặp báo cáo cho Gemini
                        else:
                            # Không gọi tool nữa thì in câu trả lời text
                            print(" "*50, end="\r") 
                            print(f"\n[🤖 Agent]:\n{msg.content}\n")
                            break
                            
                except KeyboardInterrupt:
                    print("\n[👋] Hẹn gặp lại!")
                    break
                except Exception as e:
                    print(f"\n[!] Lỗi đứt gãy luồng: {str(e)}")
                    break

def main():
    # Tắt log thừa để giao diện Terminal sạch sẽ
    litellm.suppress_debug_info = True 
    # Sửa lỗi chạy async event loop trên Windows
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_cli_agent())

if __name__ == "__main__":
    main()
