import os
from mcp.server.fastmcp import FastMCP
from codegraph.graph_engine import CodeGraphEngine

import importlib.metadata
try:
    __version__ = importlib.metadata.version("codegraph-core")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

# Khởi tạo MCP Server với tên định danh không hardcode version
mcp = FastMCP(f"CodeGraph_Enterprise_v{__version__}")

# Khởi tạo The Brain (Load in-memory graph sẵn vào RAM ở O(|V| + |E|))
# Đảm bảo Graph luôn "hot" để Agent gọi là có kết quả ngay
db_file = os.environ.get("CODEGRAPH_DB", "codegraph.sqlite")
try:
    engine = CodeGraphEngine(db_file)
    engine.load_graph()
except FileNotFoundError as e:
    print(f"⚠️ [WARNING] Server khởi động ở chế độ chờ. Chưa tìm thấy DB '{db_file}'. Cần chạy indexer trước.")
    engine = None

@mcp.tool()
def get_pruned_context(seed_node: str, top_k: int = 5, max_tokens: int = 2000) -> str:
    """
    Công cụ truy xuất Context Cắt Tỉa (Pruned Context) cho mã nguồn.
    
    Sử dụng thuật toán Personalized PageRank (PPR) để tìm các hàm, lớp, 
    hoặc biến liên quan chặt chẽ nhất về mặt logic với node mục tiêu.
    
    Args:
        seed_node: Tên của hàm/class đang cần sửa hoặc phân tích (vd: 'process_checkout')
        top_k: Số lượng node liên quan tối đa muốn trả về.
        max_tokens: Ngân sách token tối đa để tránh LLM bị "ngợp" (mặc định 2000).
    """
    if engine is None:
        return "[!] Lỗi hệ thống: Server đang chạy ở chế độ chờ. Vui lòng chạy `indexer.py` để tạo DB trước."
        
    # Gọi xuống engine đã load sẵn
    results = engine.get_context_ppr(seed_node, top_k)
    
    if not results:
        return f"[!] Không tìm thấy cấu trúc '{seed_node}' trong Codebase Graph."
    
    # [UPDATE]: Định dạng kết quả bơm code thật cho LLM với Budget Control
    context_str = f"### Báo cáo Context (Graph PPR) cho: `{seed_node}`\n"
    context_str += "> Hệ thống đã tự động tỉa cành (prune) codebase. Dưới đây là các hàm/class liên quan logic nhất.\n\n"
    
    total_tokens = 0
    for rank, item in enumerate(results, 1):
        # Thuật toán Token Budget Estimation (cải tiến theo Codebase-Memory):
        # Tính theo số từ * 1.3 thay vì chia 4 số lượng chars (chính xác hơn với comment/strings)
        word_count = len(item['source_code'].split())
        estimated_tokens = int(word_count * 1.3)
        
        if total_tokens + estimated_tokens > max_tokens:
            context_str += f"\n> ⚠️ **[TOKEN BUDGET REACHED]** Đã chạm ngưỡng {max_tokens} tokens. Đã cắt bỏ {len(results) - rank + 1} nodes kém quan trọng hơn để tránh nhiễu.\n"
            break
            
        total_tokens += estimated_tokens
        
        context_str += f"#### {rank}. [{item['kind'].upper()}] `{item['name']}` (Score: {item['score']})\n"
        context_str += f"- **File:** `{item['file_path']}`\n"
        context_str += "```python\n"
        context_str += item['source_code'] + "\n"
        context_str += "```\n\n"
        
    return context_str

@mcp.tool()
def get_callers(function_name: str) -> str:
    """
    Tìm tất cả các hàm/class đang GỌI đến (phụ thuộc vào) một hàm/class mục tiêu.
    (Upstream Discovery / Blast Radius Analysis).
    """
    if engine is None:
        return "[!] Lỗi hệ thống: Server đang chạy ở chế độ chờ. Vui lòng chạy `indexer.py` để tạo DB trước."
        
    seed_idx = None
    for rx_idx, data in engine.rx_idx_to_symbol_info.items():
        if data["name"] == function_name:
            seed_idx = rx_idx
            break
            
    if seed_idx is None:
        return f"[!] Không tìm thấy symbol '{function_name}' trong Graph."
        
    callers = []
    # Dùng reversed_graph để tìm successors (chính là callers trong graph gốc)
    for caller_idx in engine.reversed_graph.successor_indices(seed_idx):
        callers.append(engine.rx_idx_to_symbol_info[caller_idx])
        
    if not callers:
        return f"[i] '{function_name}' chưa được gọi bởi ai trong codebase này (hoặc được gọi từ bên ngoài dự án)."
        
    res = f"### Danh sách các component GỌI '{function_name}':\n"
    for c in callers:
        res += f"- [{c['kind'].upper()}] `{c['name']}` (trong `{c['file_path']}`)\n"
    return res

@mcp.tool()
def list_symbols(file_path: str = "") -> str:
    """
    Liệt kê tất cả các symbols (hàm, class) trong toàn bộ codebase, hoặc trong 1 file cụ thể.
    Giúp Agent có cái nhìn tổng quan trước khi quyết định query chi tiết.
    """
    if engine is None:
        return "[!] Lỗi hệ thống: Server đang chạy ở chế độ chờ. Vui lòng chạy `indexer.py` để tạo DB trước."
        
    # Group by file_path để output thông minh và tiết kiệm token
    grouped_symbols = {}
    total_count = 0
    
    for data in engine.rx_idx_to_symbol_info.values():
        if data["kind"] == "module": continue
        if file_path and file_path not in data["file_path"]:
            continue
            
        fp = data["file_path"]
        if fp not in grouped_symbols:
            grouped_symbols[fp] = []
            
        grouped_symbols[fp].append(data)
        total_count += 1
        
    if not grouped_symbols:
        return f"[!] Không tìm thấy symbol nào."
        
    res = f"### Danh sách Symbols{' trong `' + file_path + '`' if file_path else ' (Toàn bộ codebase)'}:\n"
    
    printed_count = 0
    for fp, syms in grouped_symbols.items():
        if printed_count >= 100: break
        
        res += f"\n📁 **File: `{fp}`**\n"
        for s in syms:
            res += f"  - [{s['kind'].upper()}] `{s['name']}`\n"
            printed_count += 1
            if printed_count >= 100:
                res += "  ... (Giới hạn hiển thị 100 symbols)\n"
                break
                
    if total_count > 100:
        res += f"\n... (Còn {total_count - printed_count} symbols nữa bị ẩn. Hãy truyền param `file_path` để xem chi tiết từng file)."
        
    return res

def main():
    # Chạy MCP Server qua stdio (Standard I/O) - Giao thức chuẩn cho AI Agents
    print("\n[⚡] MCP Server 'CodeGraph_Enterprise' đang chạy và lắng nghe Agent...")
    mcp.run(transport='stdio')

if __name__ == "__main__":
    main()
