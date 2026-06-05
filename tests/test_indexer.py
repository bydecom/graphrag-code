import unittest
import sqlite3
import os
import sys
import tempfile

# Add src directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from graphrag_code.indexer import init_db, compute_checksum, parse_python_file
from graphrag_code.graph_engine import GraphRAGCodeEngine

class TestIndexer(unittest.TestCase):
    def setUp(self):
        """Executed before each test: Create temporary SQLite database"""
        self.db_path = "test_graph.sqlite"
        # Delete stale DB files if existing due to crashes
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.conn = init_db(self.db_path)

    def tearDown(self):
        """Cleanup database artifacts after run"""
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_init_db_tables(self):
        """Verify the database schema tables (files, symbols, edges) are cleanly generated"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        self.assertIn("files", tables)
        self.assertIn("symbols", tables)
        self.assertIn("edges", tables)

    def test_checksum_consistency(self):
        """Verify cryptographic checksum consistency"""
        code = b"def test_func(): pass"
        hash1 = compute_checksum(code)
        hash2 = compute_checksum(code)
        self.assertEqual(hash1, hash2)

    def _index_source(self, source: str, filename: str = "sample.py") -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, filename)
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(source)
            parse_python_file(file_path, self.conn)

    def _edge_targets_from(self, caller_short_name: str) -> list[str]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT e.target_name
            FROM edges e
            JOIN symbols s ON e.source_id = s.id
            WHERE s.short_name = ? AND e.edge_type = 'call'
            """,
            (caller_short_name,),
        )
        return [row[0] for row in cursor.fetchall()]

    def test_assignment_based_method_resolution(self):
        """session = Session(); session.send() should resolve to Session.send."""
        self._index_source(
            """
class Session:
    def send(self):
        pass

def dispatch():
    session = Session()
    session.send()
"""
        )
        self.assertIn("Session.send", self._edge_targets_from("dispatch"))

    def test_self_method_resolution(self):
        """self.validate() inside Session should resolve to Session.validate."""
        self._index_source(
            """
class Session:
    def validate(self):
        pass

    def send(self):
        self.validate()
"""
        )
        self.assertIn("Session.validate", self._edge_targets_from("send"))

    def test_cls_method_resolution(self):
        """cls.create() inside Session should resolve to Session.create."""
        self._index_source(
            """
class Session:
    @classmethod
    def create(cls):
        pass

    def open(self):
        cls.create()
"""
        )
        self.assertIn("Session.create", self._edge_targets_from("open"))

    def test_unknown_receiver_falls_back_to_method_name(self):
        """factory.create() without assignment tracking falls back to create."""
        self._index_source(
            """
def run(factory):
    factory.create()
"""
        )
        self.assertIn("create", self._edge_targets_from("run"))
        self.assertNotIn("factory.create", self._edge_targets_from("run"))

    def _symbols_by_kind(self, kind: str) -> list[str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT short_name FROM symbols WHERE kind = ?", (kind,))
        return [row[0] for row in cursor.fetchall()]

    def _resolved_handles_targets(self, route_short_name: str) -> list[str]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT s.short_name
            FROM resolved_edges re
            JOIN symbols src ON re.source_id = src.id
            JOIN symbols s ON re.target_id = s.id
            WHERE src.short_name = ? AND re.edge_type = 'handles'
            """,
            (route_short_name,),
        )
        return [row[0] for row in cursor.fetchall()]

    def test_flask_route_decorator_creates_handles_edge(self):
        """@app.route('/users') should create route node linked to handler."""
        self._index_source(
            """
app = object()

@app.route('/users')
def get_users():
    pass
"""
        )
        self.assertIn("route:/users", self._symbols_by_kind("route"))
        self.assertEqual(self._resolved_handles_targets("route:/users"), ["get_users"])

    def test_fastapi_get_decorator_uses_http_verb_label(self):
        """@app.get('/items') should label route as 'GET /items'."""
        self._index_source(
            """
app = object()

@app.get('/items')
async def list_items():
    pass
"""
        )
        self.assertIn("GET /items", self._symbols_by_kind("route"))
        self.assertEqual(self._resolved_handles_targets("GET /items"), ["list_items"])

    def test_qualified_call_resolves_in_graph(self):
        """resolved_edges should wire qualified call targets to the right symbol."""
        self._index_source(
            """
class Session:
    def send(self):
        pass

def dispatch():
    session = Session()
    session.send()
"""
        )
        engine = GraphRAGCodeEngine(self.db_path)
        engine.load_graph()
        idx, candidates = engine.resolve_symbol("Session.send")
        self.assertIsNotNone(idx)
        self.assertEqual(len(candidates), 1)

if __name__ == "__main__":
    unittest.main()
