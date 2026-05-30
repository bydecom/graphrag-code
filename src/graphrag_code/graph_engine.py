import sqlite3
import rustworkx as rx
import os
import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
class GraphRAG-CodeEngine:
    def __init__(self, db_path="graphrag_code.sqlite"):
        self.db_path = db_path
        self.graph = rx.PyDiGraph()
        # Mapping để đối chiếu giữa SQLite ID và Rustworkx Node Index
        self.sqlite_id_to_rx_idx = {}
        self.rx_idx_to_symbol_info = {}

    def load_graph(self):
        """
        Nạp dữ liệu từ SQLite vào in-memory graph của rustworkx.
        
        Raises:
            FileNotFoundError: Nếu file database không tồn tại (chưa chạy indexer).
            RuntimeError: Nếu gặp lỗi kết nối hoặc truy vấn SQLite.
        """
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"❌ [LỖI DB] Không tìm thấy '{self.db_path}'. Vui lòng chạy indexer trước!")
            
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
        except sqlite3.Error as e:
            raise RuntimeError(f"❌ [LỖI KẾT NỐI DB] {e}")

        # 1. Load toàn bộ Symbols (Đỉnh)
        # [UPDATE]: JOIN với bảng files để lấy thêm file_path
        query_symbols = """
            SELECT s.id, s.name, s.kind, s.start_line, s.end_line, f.file_path 
            FROM symbols s
            JOIN files f ON s.file_id = f.id
        """
        cursor.execute(query_symbols)
        symbols = cursor.fetchall()
        
        for sym_id, name, kind, start, end, file_path in symbols:
            # Lưu thêm meta-data để sau này cắt code
            node_data = {
                "id": sym_id, "name": name, "kind": kind, 
                "start_line": start, "end_line": end, "file_path": file_path
            }
            rx_idx = self.graph.add_node(node_data)
            
            # Lưu lại mapping
            self.sqlite_id_to_rx_idx[sym_id] = rx_idx
            self.rx_idx_to_symbol_info[rx_idx] = node_data

        # 2. Load Edges (Cạnh) từ SQL VIEW trung tâm
        # VIEW `resolved_edges` đã xử lý cross-file logic (import/extends) — DRY (P1-3)
        query_edges = "SELECT source_id, target_id, edge_type FROM resolved_edges"
        cursor.execute(query_edges)
        edges = cursor.fetchall()

        # Build danh sách các cạnh cho rustworkx (source_idx, target_idx, edge_data)
        rx_edges = []
        for source_sqlite_id, target_sqlite_id, edge_type in edges:
            src_idx = self.sqlite_id_to_rx_idx.get(source_sqlite_id)
            tgt_idx = self.sqlite_id_to_rx_idx.get(target_sqlite_id)
            
            if src_idx is not None and tgt_idx is not None:
                # Lưu edge metadata: type + weight (P1-4 từ Audit)
                rx_edges.append((src_idx, tgt_idx, {"weight": 1.0, "type": edge_type}))

        # Add edges hàng loạt bằng C-backend
        self.graph.add_edges_from(rx_edges)
        
        # Build reversed graph cho Bidirectional PPR (P0-1 từ Audit / Reliable Graph-RAG)
        self.reversed_graph = rx.PyDiGraph()
        for idx in sorted(self.graph.node_indices()):
            self.reversed_graph.add_node(self.graph[idx])
        for src, tgt, data in self.graph.weighted_edge_list():
            self.reversed_graph.add_edge(tgt, src, data)
        
        conn.close()
        
        logging.info(f"[-] Đã nạp thành công Graph: {self.graph.num_nodes()} Nodes, {self.graph.num_edges()} Edges (+ reversed graph).")

    def _extract_source_code(self, file_path, start_line, end_line):
        """Hàm nội bộ: Đọc file và cắt đúng đoạn code cần thiết O(1) I/O"""
        # Resolve đường dẫn tuyệt đối (relative với thư mục chứa DB)
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        abs_file_path = file_path if os.path.isabs(file_path) else os.path.join(db_dir, file_path)

        if not os.path.exists(abs_file_path):
            return f"<Không tìm thấy file nguồn trên disk: {abs_file_path}>"
        
        try:
            with open(abs_file_path, 'r', encoding='utf-8') as f:
                lines = f.read().splitlines()
                # Tree-sitter là 0-indexed, slice của Python cắt đến end_line + 1
                snippet = "\n".join(lines[start_line:end_line + 1])
                return snippet
        except Exception as e:
            return f"<Lỗi đọc file: {str(e)}>"

    def _get_expanded_seeds(self, seed_idx) -> list:
        """
        [P0-2] Interface-Consumer Expansion.
        Nếu seed là Child implements Interface I, tìm luôn cả Parent (I) 
        và các Siblings (Child2) cũng implements Interface I.
        Điều này giải quyết bài toán dependency thông qua interface/abstract class.
        """
        interfaces = set()
        # Tìm tất cả interfaces mà seed implements/extends
        for succ in self.graph.successor_indices(seed_idx):
            edges = self.graph.get_all_edge_data(seed_idx, succ)
            if any(isinstance(e, dict) and e.get("type") == "extends" for e in edges):
                interfaces.add(succ)
                
        expanded_seeds = {seed_idx}
        # Từ interface, truy ngược về tất cả các consumers (classes implements interface đó)
        for iface in interfaces:
            expanded_seeds.add(iface)  # Boost điểm cho cả chính interface
            for pred in self.graph.predecessor_indices(iface):
                edges = self.graph.get_all_edge_data(pred, iface)
                if any(isinstance(e, dict) and e.get("type") == "extends" for e in edges):
                    expanded_seeds.add(pred)
                    
        return list(expanded_seeds)

    def get_context_ppr(self, seed_name: str, top_k: int = 5,
                        backward_weight: float = 0.7):
        """
        Chạy Bidirectional Personalized PageRank (P0-1 từ Audit).
        Forward PPR: tìm downstream dependencies (A gọi B → tìm B).
        Backward PPR: tìm upstream consumers/controllers (C gọi A → tìm C).
        
        Args:
            backward_weight: Hệ số cho upstream scores (0.0-1.0).
                            Mặc định 0.7 vì upstream mang ít context "how to fix" hơn.
        """
        # Tìm rx_idx của Seed Node
        seed_idx = None
        for rx_idx, data in self.rx_idx_to_symbol_info.items():
            if data["name"] == seed_name:
                seed_idx = rx_idx
                break
                
        if seed_idx is None:
            logging.warning(f"[!] Không tìm thấy symbol '{seed_name}' trong Graph.")
            return []

        logging.info(f"\n[🚀] Khởi động Bidirectional PPR từ Seed: '{seed_name}'")

        # Mở rộng seeds nếu chạm vào Interface (P0-2)
        expanded_seeds = self._get_expanded_seeds(seed_idx)
        if len(expanded_seeds) > 1:
            names = [self.rx_idx_to_symbol_info[idx]["name"] for idx in expanded_seeds]
            logging.info(f"  [+] Interface Expansion kích hoạt! Nhóm seeds: {names}")

        # Cấu hình mảng Personalization: Ép năng lượng tập trung vào cụm Seed Nodes
        personalization = {n: 0.0 for n in self.graph.node_indices()}
        for n in expanded_seeds:
            personalization[n] = 1.0 / len(expanded_seeds)

        # Weight function tương thích cả dict metadata và float legacy
        weight_fn = lambda x: x["weight"] if isinstance(x, dict) else float(x)

        # Forward PPR: downstream dependencies
        # Độ phức tạp: O(Iterations * (|V| + |E|))
        forward_scores = rx.pagerank(
            self.graph, 
            alpha=0.85, 
            weight_fn=weight_fn,
            personalization=personalization
        )

        # Backward PPR: upstream consumers (chạy trên reversed graph)
        backward_personalization = {n: 0.0 for n in self.reversed_graph.node_indices()}
        for n in expanded_seeds:
            if n in backward_personalization:
                backward_personalization[n] = 1.0 / len(expanded_seeds)
                
        backward_scores = rx.pagerank(
            self.reversed_graph,
            alpha=0.85,
            weight_fn=weight_fn,
            personalization=backward_personalization
        )

        # Merge scores: forward + backward * weight
        merged_scores = {}
        for idx in self.graph.node_indices():
            fwd = forward_scores[idx] if idx in forward_scores else 0.0
            bwd = backward_scores[idx] if idx in backward_scores else 0.0
            merged_scores[idx] = fwd + bwd * backward_weight

        # Sắp xếp các node theo điểm số (Giảm dần) - Độ phức tạp: O(|V| log |V|)
        ranked_nodes = sorted(merged_scores.items(), key=lambda item: item[1], reverse=True)

        # Trích xuất top_k kết quả (Lọc bỏ các node có điểm = 0.0 nếu có)
        pruned_context = []
        for rx_idx, score in ranked_nodes[:top_k]:
            if score > 0:
                symbol_data = self.rx_idx_to_symbol_info[rx_idx]
                
                # Gọi hàm cắt code
                source_code = self._extract_source_code(
                    symbol_data["file_path"], 
                    symbol_data["start_line"], 
                    symbol_data["end_line"]
                )
                
                pruned_context.append({
                    "name": symbol_data["name"],
                    "kind": symbol_data["kind"],
                    "score": round(score, 4),
                    "file_path": symbol_data["file_path"],
                    "source_code": source_code
                })

        return pruned_context

if __name__ == "__main__":
    import sys
    db_file = sys.argv[1] if len(sys.argv) > 1 else "graphrag_code.sqlite"
    seed_node = sys.argv[2] if len(sys.argv) > 2 else "process_checkout"
    
    engine = GraphRAG-CodeEngine(db_file)
    engine.load_graph()
    
    context = engine.get_context_ppr(seed_name=seed_node, top_k=10)
    
    logging.info(f"\n=== PRUNED CONTEXT CHO '{seed_node}' ===")
    for rank, item in enumerate(context, 1):
        logging.info(f"#{rank} | Điểm: {item['score']} | {item['kind'].capitalize()}: {item['name']}")
