import sqlite3
import json
import argparse

def export_to_json(db_path="codegraph.sqlite", out_path="graph_data.json"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Lấy danh sách nodes
    cursor.execute("SELECT id, name, kind, file_id FROM symbols")
    symbols = cursor.fetchall()
    
    # Map file_id -> tên file
    cursor.execute("SELECT id, file_path FROM files")
    files = {row[0]: row[1].split('\\')[-1].split('/')[-1] for row in cursor.fetchall()}
    
    nodes = []
    for sym_id, name, kind, file_id in symbols:
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
        
    # Lấy danh sách edges từ SQL VIEW trung tâm (DRY — P1-3)
    # Tối ưu O(1) Memory I/O: Sử dụng Cursor Iteration thay vì fetchall() để tránh tràn RAM khi có >10K cạnh
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
        
    print(f"✅ Đã xuất {len(nodes)} nodes và {len(edges)} edges ra file {out_path}!")
    conn.close()

if __name__ == "__main__":
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else "codegraph.sqlite"
    export_to_json(db_path=db)
