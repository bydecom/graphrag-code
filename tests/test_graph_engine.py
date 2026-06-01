import unittest
import sqlite3
import os
import sys

# Add src directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from graphrag_code.indexer import init_db
from graphrag_code.graph_engine import GraphRAGCodeEngine, IMPACT_BACKWARD_WEIGHT

class TestGraphEngine(unittest.TestCase):
    def setUp(self):
        """Construct Mock Graph Data for PageRank mathematical verification"""
        self.db_path = "test_engine.sqlite"
        # Safely remove old DB if exists
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass
            
        self.conn = init_db(self.db_path)
        cursor = self.conn.cursor()
        
        # 1. Mock File entry
        cursor.execute("INSERT INTO files (file_path, checksum) VALUES ('fake_module.py', 'md5hash')")
        file_id = cursor.lastrowid
        
        # 2. Mock Symbol entries with short_name to satisfy NOT NULL constraints
        symbols = [
            (file_id, "Controller", "Controller", "class", 1, 10),
            (file_id, "HelperUtils", "HelperUtils", "class", 12, 20),
            (file_id, "IBaseInterface", "IBaseInterface", "class", 22, 30)
        ]
        cursor.executemany("INSERT INTO symbols (file_id, name, short_name, kind, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?)", symbols)
        
        # Resolve mappings
        cursor.execute("SELECT id, name FROM symbols")
        sym_map = {name: sid for sid, name in cursor.fetchall()}
        
        # 3. Mock Edges: Controller ->(call)-> HelperUtils ->(extends)-> IBaseInterface
        edges = [
            (sym_map["Controller"], "HelperUtils", "call"),
            (sym_map["HelperUtils"], "IBaseInterface", "extends")
        ]
        cursor.executemany("INSERT INTO edges (source_id, target_name, edge_type) VALUES (?, ?, ?)", edges)
        self.conn.commit()

    def tearDown(self):
        """Clean up SQLite artifacts"""
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
            self.conn = None
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def test_load_graph_success(self):
        """Verify the Graph Engine successfully constructs rustworkx representation from DB"""
        engine = GraphRAGCodeEngine(self.db_path)
        engine.load_graph()
        self.assertEqual(engine.graph.num_nodes(), 3)
        self.assertEqual(engine.graph.num_edges(), 2)

    def test_db_not_found_exception(self):
        """Verify robustness: engine raises FileNotFoundError if database is missing"""
        engine = GraphRAGCodeEngine("non_existent_fake_db.sqlite")
        with self.assertRaises(FileNotFoundError):
            engine.load_graph()

    def test_bidirectional_ppr(self):
        """Upstream caller surfaces in blast-radius mode (high backward_weight).

        The engine runs two PPR passes merged by `backward_weight`, giving two query
        modes rather than one symmetric query. A pure caller has ~zero forward score,
        so it is damped at the default downstream-leaning weight and only surfaces
        once we switch to the blast-radius weight. This test exercises that mode.
        """
        engine = GraphRAGCodeEngine(self.db_path)
        engine.load_graph()

        # Blast-radius mode: high backward_weight surfaces the upstream consumer (Controller).
        context = engine.get_context_ppr(
            "HelperUtils", top_k=3, backward_weight=IMPACT_BACKWARD_WEIGHT
        )
        names = [item["name"] for item in context]

        self.assertIn("Controller", names)        # Upstream caller surfaces in blast-radius mode
        # Seed itself ("HelperUtils") and extended interface ("IBaseInterface") are in expanded_seeds,
        # so they are correctly excluded from the returned context to avoid redundancy (Issue 1)
        self.assertNotIn("HelperUtils", names)
        self.assertNotIn("IBaseInterface", names)

    def test_interface_expansion(self):
        """Verify structural Interface expansion rules"""
        engine = GraphRAGCodeEngine(self.db_path)
        engine.load_graph()
        
        # Locate HelperUtils node index
        seed_idx = None
        for rx_idx, data in engine.rx_idx_to_symbol_info.items():
            if data["name"] == "HelperUtils":
                seed_idx = rx_idx
                
        expanded = engine._get_expanded_seeds(seed_idx)
        # HelperUtils extends IBaseInterface, thus expanded seed set must contain both IDs
        self.assertGreater(len(expanded), 1)

if __name__ == "__main__":
    unittest.main()
