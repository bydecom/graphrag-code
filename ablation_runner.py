import os
import sys
import sqlite3
import numpy as np
import logging

# Make `graphrag_code` importable whether or not the package is pip-installed,
# so this script runs from the repo root regardless of the active environment.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from graphrag_code.graph_engine import GraphRAGCodeEngine

# Setup basic logging for runner
logging.getLogger().setLevel(logging.WARNING) # Suppress info logs from engine to keep output clean

def run_ablation(db_path: str, seed_name: str, top_k: int = 5, output_csv="ablation_results.csv"):
    if not os.path.exists(db_path):
        print(f"❌ Error: Database '{db_path}' not found.")
        return
        
    print(f"=== Ablation Study: Non-linear PPR Context Evaluation ===")
    print(f"Seed Node : {seed_name}")
    print(f"Database  : {db_path}")
    print(f"Output CSV: {output_csv}\n")
    
    engine = GraphRAGCodeEngine(db_path)
    engine.load_graph()
    
    # Resolve FQN for safe execution
    seed_idx = engine.get_node_index(seed_name)
    if seed_idx is None:
        print(f"❌ Error: Seed node '{seed_name}' not found in the graph.")
        return
        
    print(f"{'Weight (Bwd)':<12} | {'Rank 1 Node':<30} | {'Rank 2 Node':<30} | {'Rank 3 Node':<30}")
    print("-" * 110)
    
    csv_lines = ["backward_weight,rank,node_name,node_kind,score,fwd_score,bwd_score"]
    
    # Run from 0.0 to 1.0 (step 0.1)
    for w in np.arange(0.0, 1.1, 0.1):
        weight = float(round(w, 1))
        
        # Execute the engine with varying backward_weight
        context = engine.get_context_ppr(seed_name, top_k=top_k, backward_weight=weight)
        
        if context is None:
            # Seed node không tồn tại trong graph — abort toàn bộ ablation
            print(f"\n❌ ERROR: Seed node '{seed_name}' not found in graph.")
            print("   Run: sqlite3 <db> \"SELECT name FROM symbols LIMIT 20;\" to find valid names.")
            return

        if len(context) == 0:
            # Node tồn tại nhưng bị isolated — ghi vào CSV và tiếp tục
            print(f"{weight:<12.1f} | (Node exists but isolated — no deps or callers detected)")
            csv_lines.append(f"{weight},0,ISOLATED,,0,0,0")
            continue
            
        # Collect top 3 names for console output
        top_names = [f"{item['name']} ({item['score']:.3f})" for item in context[:3]]
        # Pad if less than 3
        while len(top_names) < 3:
            top_names.append("-")
            
        print(f"{weight:<12.1f} | {top_names[0]:<30} | {top_names[1]:<30} | {top_names[2]:<30}")
        
        # Save detailed results to CSV
        for rank, item in enumerate(context, 1):
            csv_lines.append(
                f"{weight},{rank},{item['name']},{item['kind']},{item['score']},"
                f"{item.get('fwd_score', 0)},{item.get('bwd_score', 0)}"
            )
            
    with open(output_csv, 'w', encoding='utf-8') as f:
        f.write("\n".join(csv_lines))
        
    print(f"\n✅ Ablation data successfully written to: {output_csv}")
    print("💡 Tip: Use this CSV to plot 'Rank Volatility vs Backward Weight' in your academic paper.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run PPR Ablation Study for GraphRAG-Code")
    parser.add_argument("--db", default="graphrag_code.sqlite", help="SQLite DB path")
    parser.add_argument("--seed", default="process_checkout", help="Target symbol to evaluate")
    parser.add_argument("--top_k", type=int, default=5, help="Number of context nodes to retrieve")
    parser.add_argument("--out", default="ablation_results.csv", help="Output CSV file name")
    
    args = parser.parse_args()
    run_ablation(args.db, args.seed, args.top_k, args.out)
