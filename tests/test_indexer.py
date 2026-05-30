import unittest
import sqlite3
import os
import sys

# Add src directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from graphrag_code.indexer import init_db, compute_checksum

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

if __name__ == "__main__":
    unittest.main()
