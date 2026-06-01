import os
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
from mcp.server.fastmcp import FastMCP
from graphrag_code.graph_engine import (
    GraphRAGCodeEngine,
    CONTEXT_BACKWARD_WEIGHT,
    IMPACT_BACKWARD_WEIGHT,
)

import importlib.metadata
try:
    __version__ = importlib.metadata.version("graphrag-code-core")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"

# Initialize MCP Server with version metadata
mcp = FastMCP(f"GraphRAG-Code_v{__version__}")

# Warm up in-memory graph cache in O(|V| + |E|) RAM load
# Primary env var is GRAPHRAG_CODE_DB; CODEGRAPH_DB is kept as a legacy fallback.
db_file = os.environ.get("GRAPHRAG_CODE_DB") or os.environ.get("CODEGRAPH_DB", "graphrag_code.sqlite")
try:
    engine = GraphRAGCodeEngine(db_file)
    engine.load_graph()
except FileNotFoundError as e:
    logging.warning(f"⚠️ [WARNING] Server initialized in standby mode. Database '{db_file}' not found. Please run the indexer first.")
    engine = None

def _format_disambiguation(symbol_name: str, candidates: list) -> str:
    """Render an ambiguous-symbol prompt that tells the agent how to re-query.

    Rather than silently picking the first match (which can corrupt blast-radius
    answers and evaluation seeds), we surface every candidate with its
    fully-qualified name so the next call resolves to exactly one node.
    """
    msg = (
        f"[?] Ambiguous symbol `{symbol_name}`: found {len(candidates)} matches. "
        f"Re-run this tool with one of the fully-qualified names below:\n\n"
    )
    for c in candidates:
        file_short = c["file_path"].split("/")[-1].split("\\")[-1]
        msg += (
            f"- `{c['name']}` [{c['kind'].upper()}] "
            f"in `{file_short}` (line {c['start_line'] + 1})\n"
        )
    return msg


def _resolve_or_disambiguate(symbol_name: str):
    """Resolve a symbol for a tool call.

    Returns ``(rx_idx, error_message)``:
      - unique     -> ``(idx, None)``
      - ambiguous  -> ``(None, <disambiguation prompt>)``  return the message directly
      - not found  -> ``(None, None)``  caller emits its own not-found message
    """
    idx, candidates = engine.resolve_symbol(symbol_name)
    if idx is not None:
        return idx, None
    if candidates:
        return None, _format_disambiguation(symbol_name, candidates)
    return None, None


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
        
    Note: Uses backward_weight=0.2 (default) which prioritizes downstream dependencies 
    over upstream callers. Use get_impact() for blast radius analysis.
    """
    if engine is None:
        return "[!] System Error: Standby mode active. Please run `indexer.py` to generate the DB first."

    _, ambiguity = _resolve_or_disambiguate(seed_node)
    if ambiguity:
        return ambiguity

    results = engine.get_context_ppr(seed_node, top_k)
    
    if results is None:
        return f"[!] Symbol '{seed_node}' not found in the Codebase Graph."
    if not results:
        return f"[i] Symbol '{seed_node}' exists, but has no detected dependencies or callers."
    
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

    seed_idx, ambiguity = _resolve_or_disambiguate(function_name)
    if ambiguity:
        return ambiguity
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

    _, ambiguity = _resolve_or_disambiguate(symbol_name)
    if ambiguity:
        return ambiguity

    results = engine.get_context_ppr(symbol_name, top_k=top_k, backward_weight=IMPACT_BACKWARD_WEIGHT)
    # IMPACT_BACKWARD_WEIGHT (0.9) → force PPR to lean towards upstream callers (blast radius direction)

    if results is None:
        return f"[!] Symbol '{symbol_name}' not found in the Graph."
    if not results:
        return f"[i] Symbol '{symbol_name}' exists, but has no detected dependencies or callers."

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

    seed_idx, ambiguity = _resolve_or_disambiguate(symbol_name)
    if ambiguity:
        return ambiguity

    # ── Section 1: Upstream Callers (who is calling this symbol?) ────────────────

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
        symbol_name, top_k=top_k, backward_weight=CONTEXT_BACKWARD_WEIGHT
        # CONTEXT_BACKWARD_WEIGHT (0.3) → lean towards forward/downstream to get dependencies
    )

    source_section = ""
    deps_section = ""

    if seed_idx is not None:
        seed_data = engine.rx_idx_to_symbol_info[seed_idx]
        source_code = engine._extract_source_code(
            seed_data["file_path"],
            seed_data["start_line"],
            seed_data["end_line"]
        )
        source_section = f"#### 📄 Source Code — `{symbol_name}`\n"
        source_section += f"- **File:** `{seed_data['file_path']}`\n"
        source_section += "```python\n"
        source_section += source_code + "\n"
        source_section += "```\n"
    else:
        source_section = f"#### 📄 Source Code\n- *(Symbol `{symbol_name}` not found)*\n"

    deps = ppr_results
    if deps:
        total_tokens = 0
        deps_section = f"#### ⬇️ Downstream Dependencies ({len(deps)} found)\n"
        for i, item in enumerate(deps):
            estimated = int(len(item["source_code"].split()) * 1.3)
            if total_tokens + estimated > max_tokens:
                remaining = len(deps) - i
                deps_section += (
                    f"\n> ⚠️ Token budget reached ({max_tokens} tokens). "
                    f"{remaining} more dependencies omitted.\n"
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

# ─────────────────────────────────────────────────────────────────────────────
# TOOL 3: plan_change
# One-shot PRE-EDIT briefing. Composes existing primitives (no new algorithm):
#   upstream  = get_impact's Bidirectional PPR (blast radius, ranked)
#   downstream = get_context's forward PPR (dependencies you may have to follow)
# Metadata-first by design: returns names/files/scores, NOT full source, so the
# agent gets a cheap "what should I be careful about?" answer before touching code.
# Pull actual snippets with get_context / get_pruned_context only when needed.
# ─────────────────────────────────────────────────────────────────────────────

def _change_risk(direct_caller_count: int) -> str:
    """Overall risk header derived from the number of DIRECT upstream callers.

    Single, explainable definition (GitNexus-style thresholds) — deliberately
    NOT mixed with the per-row PPR confidence tiers used inside get_impact.
    """
    if direct_caller_count >= 21:
        return "🔴 HIGH"
    if direct_caller_count >= 6:
        return "🟡 MEDIUM"
    return "🟢 LOW"


@mcp.tool()
def plan_change(
    symbol_name: str,
    top_k_upstream: int = 8,
    top_k_downstream: int = 5,
    include_snippets: bool = False,
) -> str:
    """
    PRE-EDIT change plan — call this BEFORE modifying a function or class.

    Produces a single, token-light briefing so an agent knows the blast radius
    and dependencies up front, instead of editing blind. Composes two existing
    PPR passes:
      - Upstream (blast radius): who breaks if this changes — ranked by
        Bidirectional PPR, so strong indirect callers (hop 2+) surface, not just
        direct callers.
      - Downstream (dependencies): what this relies on and may need to follow.

    Risk level (header) is based purely on the count of DIRECT callers — a
    factual graph signal, not an LLM recommendation.

    Args:
        symbol_name: The function/class you are about to modify.
        top_k_upstream: Max ranked upstream (blast radius) symbols (default: 8).
        top_k_downstream: Max ranked downstream dependency symbols (default: 5).
        include_snippets: If True, append the seed's source code (off by default
                          to keep the plan compact — use get_context for full code).

    Returns:
        Markdown briefing: Risk → Blast Radius (upstream) → Dependencies
        (downstream) → Affected files. No source code unless include_snippets.
    """
    if engine is None:
        return "[!] System Error: Standby mode. Please run the indexer first."

    seed_idx, ambiguity = _resolve_or_disambiguate(symbol_name)
    if ambiguity:
        return ambiguity
    if seed_idx is None:
        return f"[!] Symbol '{symbol_name}' not found in the Graph."

    # ── Direct callers (depth-1) — drives the overall risk header ───────────────
    direct_callers = [
        engine.rx_idx_to_symbol_info[idx]
        for idx in engine.reversed_graph.successor_indices(seed_idx)
    ]
    risk = _change_risk(len(direct_callers))

    # ── Upstream blast radius (ranked) ──────────────────────────────────────────
    upstream = engine.get_context_ppr(
        symbol_name, top_k=top_k_upstream, backward_weight=IMPACT_BACKWARD_WEIGHT
    ) or []
    upstream = [r for r in upstream if r["name"] != symbol_name]

    # ── Downstream dependencies (ranked) ────────────────────────────────────────
    downstream = engine.get_context_ppr(
        symbol_name, top_k=top_k_downstream, backward_weight=CONTEXT_BACKWARD_WEIGHT
    ) or []
    downstream = [r for r in downstream if r["name"] != symbol_name]

    seed_data = engine.rx_idx_to_symbol_info[seed_idx]
    seed_file = seed_data["file_path"]

    # ── Assemble report ─────────────────────────────────────────────────────────
    res = f"### Change Plan for `{symbol_name}`\n"
    res += f"> **Overall Risk: {risk}** — based on {len(direct_callers)} direct caller(s).\n\n"

    # Direct callers (depth-1) — the symbols that break first on a breaking change.
    # Listed by name (metadata only) so the agent doesn't have to infer them from
    # the PPR table, which is ranked by relevance rather than call-distance.
    if direct_callers:
        res += f"#### 🎯 Direct Callers ({len(direct_callers)})\n"
        for c in direct_callers:
            file_short = c["file_path"].split("/")[-1].split("\\")[-1]
            res += f"- `{c['name']}` [{c['kind'].upper()}] in `{file_short}`\n"
        res += "\n"

    # Blast radius (upstream)
    res += f"#### ⬆️ Blast Radius — Upstream (ranked by PPR)\n"
    if upstream:
        res += "| Rank | Symbol | File | PPR Score |\n"
        res += "|------|--------|------|-----------|\n"
        for rank, item in enumerate(upstream, 1):
            file_short = item["file_path"].split("/")[-1].split("\\")[-1]
            res += f"| {rank} | `{item['name']}` | `{file_short}` | {item['score']} |\n"
    elif direct_callers:
        res += "- *(Callers exist but scored below threshold — see `get_impact` for the full table.)*\n"
    else:
        res += "- *(No callers — likely an entry point or top-level symbol. Low breakage risk.)*\n"

    # Dependencies (downstream)
    res += f"\n#### ⬇️ Dependencies — Downstream (ranked by PPR)\n"
    if downstream:
        res += "| Rank | Symbol | File | PPR Score |\n"
        res += "|------|--------|------|-----------|\n"
        for rank, item in enumerate(downstream, 1):
            file_short = item["file_path"].split("/")[-1].split("\\")[-1]
            res += f"| {rank} | `{item['name']}` | `{file_short}` | {item['score']} |\n"
    else:
        res += "- *(No significant downstream dependencies detected.)*\n"

    # Affected files — factual aggregation, no advice.
    # Union of direct callers + ranked upstream/downstream, so a direct caller's
    # file is never dropped just because it fell outside top_k of the PPR table.
    affected_files = []
    for item in direct_callers + upstream + downstream:
        fp = item["file_path"]
        if fp != seed_file and fp not in affected_files:
            affected_files.append(fp)
    res += f"\n#### 📁 Affected Files ({len(affected_files)})\n"
    if affected_files:
        for fp in affected_files:
            res += f"- `{fp}`\n"
    else:
        res += f"- *(Changes appear contained within `{seed_file}`.)*\n"

    # Optional seed source — off by default to keep the plan compact
    if include_snippets:
        source_code = engine._extract_source_code(
            seed_file, seed_data["start_line"], seed_data["end_line"]
        )
        res += f"\n#### 📄 Source — `{symbol_name}`\n"
        res += f"- **File:** `{seed_file}`\n"
        res += "```python\n" + source_code + "\n```\n"

    res += (
        f"\n> ℹ️ Metadata-only plan. Upstream/downstream ranked by Bidirectional PPR "
        f"(relevance, not call-distance). For full source, call `get_context`."
    )
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
