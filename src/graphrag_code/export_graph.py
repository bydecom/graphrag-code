import sqlite3
import json
import argparse

def export_to_json(db_path="graphrag_code.sqlite", out_path="graph_data.json"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Map file_id -> file name
    cursor.execute("SELECT id, file_path FROM files")
    files = {row[0]: row[1].split('\\')[-1].split('/')[-1] for row in cursor.fetchall()}
    
    nodes = []
    # O(1) Memory I/O: Use Cursor Iteration instead of fetchall() to avoid RAM overflow
    for sym_id, name, kind, file_id in cursor.execute("SELECT id, name, kind, file_id FROM symbols"):
        file_name = files.get(file_id, "Unknown")
        
        if kind == 'module':
            group = 'module'
            label = f"📁 {name.replace('<module: ', '').replace('>', '')}"
        elif kind == 'class':
            group = 'class'
            label = f"📦 {name}"
        else:
            group = 'function'
            label = f"⚙️ {name}\n({file_name})"
            
        nodes.append({
            "id": sym_id,
            "label": label,
            "group": group,
            "title": f"File: {file_name} | Type: {kind}"
        })
        
    # Get edges from central SQL VIEW (DRY — P1-3)
    # Optimized O(1) Memory I/O
    edges = []
    for src_id, tgt_id, edge_type in cursor.execute("SELECT source_id, target_id, edge_type FROM resolved_edges"):
        edges.append({
            "from": src_id,
            "to": tgt_id,
            "label": edge_type,
            "arrows": "to",
            "color": {"color": "#ff5722" if edge_type == 'import' else "#2196f3"}
        })
        
    graph_data = {"nodes": nodes, "edges": edges}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, ensure_ascii=False, indent=2)
        
    print(f"✅ Successfully exported {len(nodes)} nodes and {len(edges)} edges to {out_path}!")
    conn.close()

def main():
    parser = argparse.ArgumentParser(description="Export Codebase Knowledge Graph to JSON")
    parser.add_argument("--db", default="graphrag_code.sqlite", help="Path to SQLite database")
    parser.add_argument("--out", default="graph_data.json", help="Path to output JSON")
    args = parser.parse_args()
    export_to_json(args.db, args.out)

if __name__ == "__main__":
    main()
