import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
import sqlite3
import hashlib
import os
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

def init_db(db_path="codegraph.sqlite"):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    # 1. Bảng quản lý File
    c.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT UNIQUE NOT NULL,
        checksum TEXT NOT NULL,
        last_parsed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    # 2. Bảng quản lý Đỉnh (Nodes)
    c.execute("""
    CREATE TABLE IF NOT EXISTS symbols (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
    )
    """)
    # 3. Bảng quản lý Cạnh (Edges) — UNIQUE constraint chống duplicate (P0-3)
    c.execute("""
    CREATE TABLE IF NOT EXISTS edges (
        source_id INTEGER NOT NULL,
        target_name TEXT NOT NULL,
        edge_type TEXT NOT NULL,
        UNIQUE(source_id, target_name, edge_type),
        FOREIGN KEY (source_id) REFERENCES symbols(id) ON DELETE CASCADE
    )
    """)
    # Indexes chống bottleneck khi load vào in-memory graph
    c.execute("CREATE INDEX IF NOT EXISTS idx_files_path ON files(file_path)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_name)")
    # SQL VIEW trung tâm: resolve edges cross-file (P1-3 — DRY cho graph_engine + export)
    c.execute("DROP VIEW IF EXISTS resolved_edges")
    c.execute("""
    CREATE VIEW IF NOT EXISTS resolved_edges AS
        SELECT e.source_id, s.id AS target_id, e.edge_type
        FROM edges e
        INNER JOIN symbols s ON e.target_name = s.name
        INNER JOIN symbols src ON e.source_id = src.id
        WHERE s.file_id = src.file_id
           OR e.edge_type IN ('import', 'extends')
           OR EXISTS (
               SELECT 1 FROM edges e_imp
               INNER JOIN symbols s_mod ON e_imp.source_id = s_mod.id
               WHERE s_mod.file_id = src.file_id
                 AND e_imp.edge_type = 'import'
                 AND e_imp.target_name = e.target_name
           )
    """)
    conn.commit()
    return conn

# Khởi tạo Tree-sitter Parser
PY_LANGUAGE = Language(tspython.language())
parser = Parser(PY_LANGUAGE)

# Query nâng cấp: function, class, inheritance, calls, imports (P1-5: thêm extends)
QUERY_SCM = """
(function_definition name: (identifier) @symbol.function)
(class_definition name: (identifier) @symbol.class)
(class_definition superclasses: (argument_list (identifier) @edge.extends))
(call function: (identifier) @edge.call)
(call function: (attribute attribute: (identifier) @edge.call))
(import_statement name: (dotted_name) @edge.import)
(import_from_statement name: (dotted_name) @edge.import)
"""
query = PY_LANGUAGE.query(QUERY_SCM)

def compute_checksum(source_code: bytes) -> str:
    return hashlib.md5(source_code).hexdigest()

def find_enclosing_symbol(node, source_code: bytes, module_name: str) -> str:
    """
    Leo ngược cây AST để tìm tên của function/class chứa node hiện tại.
    Độ phức tạp: O(Tree Depth) ~ O(1) thực tế.
    """
    curr = node.parent
    while curr is not None:
        if curr.type in ('function_definition', 'class_definition'):
            # Tìm node con có type là 'identifier' để lấy tên symbol
            for child in curr.children:
                if child.type == 'identifier':
                    return source_code[child.start_byte:child.end_byte].decode('utf8')
        curr = curr.parent
    return module_name

def parse_python_file(file_path, conn):
    try:
        with open(file_path, "rb") as f:
            source_code = f.read()
    except Exception as e:
        logging.info(f"❌ [LỖI I/O] Bỏ qua file '{file_path}': {e}")
        return
        
    checksum = compute_checksum(source_code)
    cursor = conn.cursor()
    
    # 1. Cơ chế Incremental Parsing
    try:
        cursor.execute("SELECT id, checksum FROM files WHERE file_path = ?", (file_path,))
    except sqlite3.OperationalError as e:
        logging.info(f"❌ [LỖI DB] Database chưa được khởi tạo đúng cách: {e}")
        return

    row = cursor.fetchone()
    if row:
        file_id, old_checksum = row
        if old_checksum == checksum:
            logging.info(f"[SKIP] '{file_path}' không có thay đổi (Checksum khớp).")
            return
        else:
            logging.info(f"[UPDATE] '{file_path}' đã thay đổi. Đang parse lại...")
            # Xóa các symbols cũ (cascade xoá edges)
            cursor.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
            cursor.execute("UPDATE files SET checksum = ?, last_parsed = CURRENT_TIMESTAMP WHERE id = ?", (checksum, file_id))
    else:
        logging.info(f"[NEW] Bắt đầu parse '{file_path}'...")
        cursor.execute("INSERT INTO files (file_path, checksum) VALUES (?, ?)", (file_path, checksum))
        file_id = cursor.lastrowid
        
    # 2. Parse source code ra AST
    tree = parser.parse(source_code)
    captures = query.captures(tree.root_node)
    
    # Chuẩn hóa capture API cho các version tree-sitter khác nhau
    if isinstance(captures, dict):
        capture_items = [(node, name) for name, nodes in captures.items() for node in nodes]
    else:
        capture_items = captures

    symbol_map = {}
    
    # [NEW]: Đăng ký node Module (đại diện cho file)
    module_name = f"<module: {os.path.basename(file_path)}>"
    cursor.execute(
        "INSERT INTO symbols (file_id, name, kind, start_line, end_line) VALUES (?, ?, ?, ?, ?)",
        (file_id, module_name, "module", 0, 0)
    )
    symbol_map[module_name] = cursor.lastrowid
    logging.info(f"  [+] Đỉnh: Module '{module_name}'")
    
    # 3. Quét lần 1: Lưu tất cả các symbol (Node)
    for node, capture_name in capture_items:
        if capture_name in ('symbol.function', 'symbol.class'):
            name = source_code[node.start_byte:node.end_byte].decode('utf8')
            kind = capture_name.split('.')[1]
            
            # [FIX BUG 1]: Lấy block node (parent) thay vì identifier node
            block_node = node.parent if node.parent else node
            
            # Xử lý tương thích API của Point object
            start_line = getattr(block_node.start_point, 'row', None)
            if start_line is None: start_line = block_node.start_point[0]
            end_line = getattr(block_node.end_point, 'row', None)
            if end_line is None: end_line = block_node.end_point[0]
            
            cursor.execute(
                "INSERT INTO symbols (file_id, name, kind, start_line, end_line) VALUES (?, ?, ?, ?, ?)",
                (file_id, name, kind, start_line, end_line)
            )
            symbol_id = cursor.lastrowid
            symbol_map[name] = symbol_id
            logging.info(f"  [+] Đỉnh: {kind.capitalize()} '{name}' (ID: {symbol_id}, Dòng: {start_line}-{end_line})")
            
            # [FIX BUG 3]: Thêm cạnh 'contains' nếu hàm nằm trong class
            if kind == 'function':
                parent_name = find_enclosing_symbol(block_node, source_code, module_name)
                parent_id = symbol_map.get(parent_name)
                if parent_id:
                    cursor.execute(
                        "INSERT INTO edges (source_id, target_name, edge_type) VALUES (?, ?, ?)",
                        (parent_id, name, 'contains')
                    )
                    logging.info(f"  [->] Cạnh: '{parent_name}' chứa hàm '{name}'")

    BUILTIN_IGNORE = {'print', 'len', 'range', 'str', 'int', 'list', 'dict', 'isinstance', 'type', 'super', 'enumerate', 'zip'}

    # 4. Quét lần 2: Lưu các edges (call, import, extends) với Context Tracking
    for node, capture_name in capture_items:
        if capture_name in ('edge.call', 'edge.import', 'edge.extends'):
            target_name = source_code[node.start_byte:node.end_byte].decode('utf8')
            if '.' in target_name:
                target_name = target_name.split('.')[-1]
                
            edge_type = capture_name.split('.')[1]  # 'call', 'import', hoặc 'extends'
            
            # Lọc bỏ các hàm built-in gây nhiễu
            if edge_type == 'call' and target_name in BUILTIN_IGNORE:
                continue
            
            # Gọi hàm leo ngược AST (Context Tracking) để giải quyết source_id
            caller_name = find_enclosing_symbol(node, source_code, module_name)
            source_id = symbol_map.get(caller_name)
            
            if source_id:
                # INSERT OR IGNORE: tận dụng UNIQUE constraint, tránh duplicate (P0-3)
                cursor.execute(
                    "INSERT OR IGNORE INTO edges (source_id, target_name, edge_type) VALUES (?, ?, ?)",
                    (source_id, target_name, edge_type)
                )
                logging.info(f"  [->] Cạnh: '{caller_name}' --[{edge_type}]--> '{target_name}'")

    conn.commit()
    logging.info(f"✅ Hoàn tất lưu file '{file_path}' vào SQLite!\n")

import argparse

def scan_directory(directory_path, conn):
    logging.info(f"🔍 Bắt đầu quét thư mục: {directory_path}")
    py_files_count = 0
    for root, _, files in os.walk(directory_path):
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                parse_python_file(file_path, conn)
                py_files_count += 1
    
    logging.info(f"\n✅ Đã quét xong {py_files_count} file Python trong codebase.")

def main():
    cli_parser = argparse.ArgumentParser(description="Codebase Knowledge Graph Indexer")
    cli_parser.add_argument("target_path", nargs="?", default="sample_app.py", help="Đường dẫn tới file hoặc thư mục cần parse (mặc định: sample_app.py)")
    cli_parser.add_argument("--db", default="codegraph.sqlite", help="Đường dẫn tới file SQLite (mặc định: codegraph.sqlite)")
    args = cli_parser.parse_args()

    logging.info(f"Khởi tạo database: {args.db}")
    conn = init_db(args.db)
    
    target_path = args.target_path
    if not os.path.exists(target_path):
        logging.info(f"❌ Lỗi: Không tìm thấy đường dẫn '{target_path}'")
    else:
        if os.path.isdir(target_path):
            scan_directory(target_path, conn)
        else:
            parse_python_file(target_path, conn)
    
    conn.close()

if __name__ == "__main__":
    main()
