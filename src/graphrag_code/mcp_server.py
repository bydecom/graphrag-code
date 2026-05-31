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


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 1: get_impact
# Blast radius with PPR confidence scores — our key differentiator from GitNexus
# GitNexus uses BFS (flat list). We use Bidirectional PPR (ranked scores).
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_impact(symbol_name: str, top_k: int = 10) -> str:
    """
    Blast Radius Analysis with PPR Confidence Scores.

    Unlike flat BFS traversal, this tool uses Bidirectional Personalized PageRank
    to rank ALL affected symbols by their mathematical dependency strength.
    Each result includes a confidence tier (High / Medium / Low) so the AI agent
    knows which files to prioritize when making changes.

    Args:
        symbol_name: The function or class you are about to modify.
        top_k: Maximum number of impacted symbols to return (default: 10).

    Returns:
        Ranked list of symbols likely affected, with PPR scores and confidence tiers.
    """
    if engine is None:
        return "[!] System Error: Standby mode. Please run the indexer first."

    results = engine.get_context_ppr(symbol_name, top_k=top_k, backward_weight=0.9)
    # backward_weight=0.9 → force PPR to lean towards upstream callers (blast radius direction)

    if not results:
        return f"[!] Symbol '{symbol_name}' not found in the Graph."

    # Find the seed node to exclude from the results (no need to report itself)
    seed_filtered = [r for r in results if r["name"] != symbol_name]

    if not seed_filtered:
        return f"[i] '{symbol_name}' has no detected dependents in this codebase."

    # Calculate confidence tier based on percentile PPR score
    scores = [r["score"] for r in seed_filtered]
    max_score = max(scores) if scores else 1.0
    
    def confidence_tier(score: float) -> str:
        ratio = score / max_score if max_score > 0 else 0
        if ratio >= 0.6:
            return "🔴 HIGH"
        elif ratio >= 0.3:
            return "🟡 MEDIUM"
        else:
            return "🟢 LOW"

    res = f"### Impact Analysis for `{symbol_name}` (Bidirectional PPR)\n"
    res += f"> Ranked by dependency strength. Modify **HIGH** confidence items with care.\n\n"
    res += f"| Rank | Confidence | Symbol | File | PPR Score |\n"
    res += f"|------|-----------|--------|------|-----------|\n"

    for rank, item in enumerate(seed_filtered, 1):
        tier = confidence_tier(item["score"])
        file_short = item["file_path"].split("/")[-1].split("\\")[-1]
        res += (
            f"| {rank} | {tier} | `{item['name']}` "
            f"| `{file_short}` | {item['score']} |\n"
        )

    res += f"\n**Total impacted symbols:** {len(seed_filtered)}\n"
    res += (
        f"\n> ℹ️ Scores are Bidirectional PPR values — "
        f"higher means stronger structural coupling to `{symbol_name}`."
    )
    return res


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 2: get_context
# 360° structural view — merges get_callers + get_pruned_context into 1 call
# Reduces the number of Agent tool calls from 2-3 down to 1
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_context(symbol_name: str, top_k: int = 5, max_tokens: int = 1500) -> str:
    """
    360° Structural View — Complete context in a single tool call.

    Combines upstream callers (who depends on this?) + downstream dependencies
    (what does this call?) + actual source code into one structured response.
    Reduces agent tool call overhead compared to calling get_callers and
    get_pruned_context separately.

    Args:
        symbol_name: The function or class to analyze.
        top_k: Number of related symbols to include in dependency context.
        max_tokens: Token budget for the source code section (default: 1500).

    Returns:
        Structured report: Callers → Source Code → Dependencies.
    """
    if engine is None:
        return "[!] System Error: Standby mode. Please run the indexer first."

    # ── Section 1: Upstream Callers (who is calling this symbol?) ────────────────
    seed_idx = None
    for rx_idx, data in engine.rx_idx_to_symbol_info.items():
        if data["name"] == symbol_name:
            seed_idx = rx_idx
            break

    callers_section = ""
    if seed_idx is not None:
        callers = [
            engine.rx_idx_to_symbol_info[idx]
            for idx in engine.reversed_graph.successor_indices(seed_idx)
        ]
        if callers:
            callers_section = f"#### ⬆️ Upstream Callers ({len(callers)} found)\n"
            for c in callers:
                file_short = c["file_path"].split("/")[-1].split("\\")[-1]
                callers_section += f"- `{c['name']}` [{c['kind'].upper()}] in `{file_short}`\n"
        else:
            callers_section = (
                "#### ⬆️ Upstream Callers\n"
                "- *(No callers found — this may be an entry point or top-level symbol)*\n"
            )
    else:
        callers_section = (
            f"#### ⬆️ Upstream Callers\n"
            f"- *(Symbol `{symbol_name}` not found in graph)*\n"
        )

    # ── Section 2: Source Code + Downstream Dependencies (PPR forward) ───────
    ppr_results = engine.get_context_ppr(
        symbol_name, top_k=top_k, backward_weight=0.3
        # backward_weight=0.3 → lean towards forward/downstream to get dependencies
    )

    source_section = ""
    deps_section = ""

    if not ppr_results:
        source_section = f"#### 📄 Source Code\n- *(Symbol `{symbol_name}` not found)*\n"
    else:
        # The first symbol in PPR is usually the seed node itself (highest score)
        seed_result = next((r for r in ppr_results if r["name"] == symbol_name), ppr_results[0])

        source_section = f"#### 📄 Source Code — `{seed_result['name']}`\n"
        source_section += f"- **File:** `{seed_result['file_path']}`\n"
        source_section += "```python\n"
        source_section += seed_result["source_code"] + "\n"
        source_section += "```\n"

        # The remainder are downstream dependencies
        deps = [r for r in ppr_results if r["name"] != symbol_name]
        if deps:
            total_tokens = 0
            deps_section = f"#### ⬇️ Downstream Dependencies ({len(deps)} found)\n"
            for item in deps:
                estimated = int(len(item["source_code"].split()) * 1.3)
                if total_tokens + estimated > max_tokens:
                    deps_section += (
                        f"\n> ⚠️ Token budget reached ({max_tokens} tokens). "
                        f"{len(deps) - deps.index(item)} more dependencies omitted.\n"
                    )
                    break
                total_tokens += estimated
                file_short = item["file_path"].split("/")[-1].split("\\")[-1]
                deps_section += f"\n**`{item['name']}`** [{item['kind'].upper()}] "
                deps_section += f"— `{file_short}` (PPR: {item['score']})\n"
                deps_section += "```python\n"
                deps_section += item["source_code"] + "\n"
                deps_section += "```\n"
        else:
            deps_section = (
                "#### ⬇️ Downstream Dependencies\n"
                "- *(No significant downstream dependencies detected)*\n"
            )

    # ── Assemble final report ─────────────────────────────────────────────────
    report = f"### 360° Context Report for `{symbol_name}`\n\n"
    report += callers_section + "\n"
    report += source_section + "\n"
    report += deps_section

    return report

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
