import os
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
from mcp.server.fastmcp import FastMCP
from graphrag_code.graph_engine import GraphRAGCodeEngine

import importlib.metadata
try:
    __version__ = importlib.metadata.version("graphrag-code-core")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

# Initialize MCP Server with version metadata
mcp = FastMCP(f"GraphRAG-Code_v{__version__}")

# Warm up in-memory graph cache in O(|V| + |E|) RAM load
db_file = os.environ.get("CODEGRAPH_DB", "graphrag_code.sqlite")
try:
    engine = GraphRAGCodeEngine(db_file)
    engine.load_graph()
except FileNotFoundError as e:
    logging.warning(f"⚠️ [WARNING] Server initialized in standby mode. Database '{db_file}' not found. Please run the indexer first.")
    engine = None

@mcp.tool()
def get_pruned_context(seed_node: str, top_k: int = 5, max_tokens: int = 2000) -> str:
    """
    Retrieves the Pruned Context for source code nodes.
    
    Uses Personalized PageRank (PPR) to traverse the AST dependency graph and find the 
    most logically related functions, classes, or imports relative to the target seed node.
    
    Args:
        seed_node: Name of the function/class being modified or analyzed (e.g., 'process_checkout')
        top_k: Maximum number of related nodes to return.
        max_tokens: Maximum token budget to prevent LLM overload (default 2000).
    """
    if engine is None:
        return "[!] System Error: Standby mode active. Please run `indexer.py` to generate the DB first."
        
    results = engine.get_context_ppr(seed_node, top_k)
    
    if not results:
        return f"[!] Structure '{seed_node}' not found in the Codebase Graph."
    
    # Format output for LLM context injection with token budget controls
    context_str = f"### Context Report (Graph PPR) for: `{seed_node}`\n"
    context_str += "> Codebase dynamically pruned. The following code snippets represent the highest scoring dependency paths:\n\n"
    
    total_tokens = 0
    for rank, item in enumerate(results, 1):
        # Token Budget Estimation:
        # Calculated via word count * 1.3 instead of character split / 4 (tighter fit for comments/code)
        word_count = len(item['source_code'].split())
        estimated_tokens = int(word_count * 1.3)
        
        if total_tokens + estimated_tokens > max_tokens:
            context_str += f"\n> ⚠️ **[TOKEN BUDGET REACHED]** Target limit of {max_tokens} tokens reached. Pruned {len(results) - rank + 1} less significant nodes to avoid context clutter.\n"
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
    Finds all component nodes calling or depending on the target node.
    (Upstream Discovery / Blast Radius Analysis).
    """
    if engine is None:
        return "[!] System Error: Standby mode active. Please run `indexer.py` to generate the DB first."
        
    seed_idx = None
    for rx_idx, data in engine.rx_idx_to_symbol_info.items():
        if data["name"] == function_name:
            seed_idx = rx_idx
            break
            
    if seed_idx is None:
        return f"[!] Symbol '{function_name}' not found in the Graph."
        
    callers = []
    # Use reversed graph to retrieve successors (which represents upstream callers in original graph)
    for caller_idx in engine.reversed_graph.successor_indices(seed_idx):
        callers.append(engine.rx_idx_to_symbol_info[caller_idx])
        
    if not callers:
        return f"[i] '{function_name}' is not called by any component in this codebase (or called dynamically externally)."
        
    res = f"### Upstream Callers for '{function_name}':\n"
    for c in callers:
        res += f"- [{c['kind'].upper()}] `{c['name']}` (in `{c['file_path']}`)\n"
    return res

@mcp.tool()
def list_symbols(file_path: str = "") -> str:
    """
    Lists all symbols (functions, classes) in the codebase, or filtered by a specific file path.
    Enables initial structural discovery for AI Agents.
    """
    if engine is None:
        return "[!] System Error: Standby mode active. Please run `indexer.py` to generate the DB first."
        
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
        return f"[!] No symbols found."
        
    res = f"### Codebase Symbols{' in `' + file_path + '`' if file_path else ' (Full Codebase)'}:\n"
    
    printed_count = 0
    for fp, syms in grouped_symbols.items():
        if printed_count >= 100: break
        
        res += f"\n📁 **File: `{fp}`**\n"
        for s in syms:
            res += f"  - [{s['kind'].upper()}] `{s['name']}`\n"
            printed_count += 1
            if printed_count >= 100:
                res += "  ... (Output capped at 100 symbols)\n"
                break
                
    if total_count > 100:
        res += f"\n... ({total_count - printed_count} remaining symbols hidden. Pass `file_path` to view specific files)."
        
    return res

def main():
    # Run the MCP Server over standard I/O (stdio)
    logging.info("\n[⚡] MCP Server 'GraphRAG-Code' is running and listening for AI Agents...")
    mcp.run(transport='stdio')

if __name__ == "__main__":
    main()
