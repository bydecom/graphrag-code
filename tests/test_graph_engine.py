import unittest
import sqlite3
import os
import sys

# Đưa path của src vào
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from codegraph.indexer import init_db
from codegraph.graph_engine import CodeGraphEngine

class TestGraphEngine(unittest.TestCase):
    def setUp(self):
        """Tạo dữ liệu đồ thị Mock (Fake Data) để test thuật toán PPR"""
        self.db_path = "test_engine.sqlite"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
            
        self.conn = init_db(self.db_path)
        cursor = self.conn.cursor()
        
        # 1. Tạo File ảo
        cursor.execute("INSERT INTO files (file_path, checksum) VALUES ('fake_module.py', 'md5hash')")
        file_id = cursor.lastrowid
        
        # 2. Tạo Symbol ảo
        symbols = [
            (file_id, "Controller", "class", 1, 10),
            (file_id, "HelperUtils", "class", 12, 20),
            (file_id, "IBaseInterface", "class", 22, 30)
        ]
        cursor.executemany("INSERT INTO symbols (file_id, name, kind, start_line, end_line) VALUES (?, ?, ?, ?, ?)", symbols)
        
        # Lấy lại mapping ID
        cursor.execute("SELECT id, name FROM symbols")
        sym_map = {name: sid for sid, name in cursor.fetchall()}
        
        # 3. Tạo Edges ảo: Controller ->(call)-> HelperUtils ->(extends)-> IBaseInterface
        edges = [
            (sym_map["Controller"], "HelperUtils", "call"),
            (sym_map["HelperUtils"], "IBaseInterface", "extends")
        ]
        cursor.executemany("INSERT INTO edges (source_id, target_name, edge_type) VALUES (?, ?, ?)", edges)
        self.conn.commit()

    def tearDown(self):
        """Dọn dẹp"""
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_load_graph_success(self):
        """Kiểm tra Graph Engine nạp SQLite thành công vào in-memory rustworkx"""
        engine = CodeGraphEngine(self.db_path)
        engine.load_graph()
        self.assertEqual(engine.graph.num_nodes(), 3)
        self.assertEqual(engine.graph.num_edges(), 2)

    def test_db_not_found_exception(self):
        """Kiểm tra Robustness: Quăng lỗi FileNotFoundError nếu DB thiếu"""
        engine = CodeGraphEngine("non_existent_fake_db.sqlite")
        with self.assertRaises(FileNotFoundError):
            engine.load_graph()

    def test_bidirectional_ppr(self):
        """Kiểm tra thuật toán Bidirectional Personalized PageRank"""
        engine = CodeGraphEngine(self.db_path)
        engine.load_graph()
        
        # Chạy PPR với HelperUtils
        # Do là Bidirectional: nó phải tìm thấy IBaseInterface (forward) và Controller (backward)
        context = engine.get_context_ppr("HelperUtils", top_k=3)
        names = [item["name"] for item in context]
        
        self.assertIn("HelperUtils", names) # Bản thân nó
        self.assertIn("Controller", names)  # Caller của nó
        self.assertIn("IBaseInterface", names) # Dependency của nó

    def test_interface_expansion(self):
        """Kiểm tra logic P0-2: Mở rộng cụm Seed nếu chạm vào Interface"""
        engine = CodeGraphEngine(self.db_path)
        engine.load_graph()
        
        # Tìm ID của HelperUtils
        seed_idx = None
        for rx_idx, data in engine.rx_idx_to_symbol_info.items():
            if data["name"] == "HelperUtils":
                seed_idx = rx_idx
                
        expanded = engine._get_expanded_seeds(seed_idx)
        # Vì HelperUtils extends IBaseInterface, expanded seeds phải chứa cả 2 ID này
        self.assertGreater(len(expanded), 1)

if __name__ == "__main__":
    unittest.main()
