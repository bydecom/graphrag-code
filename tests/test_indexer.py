import unittest
import sqlite3
import os
import sys

# Thêm thư mục gốc vào path để có thể import các module của MVP
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from codegraph.indexer import init_db, compute_checksum

class TestIndexer(unittest.TestCase):
    def setUp(self):
        """Chạy trước mỗi test: Tạo database SQLite tạm trên memory hoặc file nháp"""
        self.db_path = "test_graph.sqlite"
        # Xoá file cũ nếu tồn tại do crash từ test trước
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.conn = init_db(self.db_path)

    def tearDown(self):
        """Dọn dẹp sau mỗi test"""
        self.conn.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_init_db_tables(self):
        """Kiểm tra xem schema cơ bản (files, symbols, edges) có được tạo không"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        self.assertIn("files", tables)
        self.assertIn("symbols", tables)
        self.assertIn("edges", tables)
        
    def test_init_db_views(self):
        """Kiểm tra xem SQL VIEW 'resolved_edges' để join cross-file có được tạo không"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='view'")
        views = [row[0] for row in cursor.fetchall()]
        self.assertIn("resolved_edges", views)

    def test_compute_checksum(self):
        """Kiểm tra tính năng checksum MD5 để phục vụ Incremental Parsing"""
        code1 = b"def hello(): pass"
        code2 = b"def hello(): return 1"
        
        self.assertEqual(compute_checksum(code1), compute_checksum(code1))
        self.assertNotEqual(compute_checksum(code1), compute_checksum(code2))

if __name__ == "__main__":
    unittest.main()
