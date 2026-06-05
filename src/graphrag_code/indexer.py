import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
import sqlite3
import hashlib
import os
import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Query, QueryCursor

def init_db(db_path="graphrag_code.sqlite"):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    # 1. File Management Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT UNIQUE NOT NULL,
        checksum TEXT NOT NULL,
        last_parsed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    # 2. Nodes/Symbols Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS symbols (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        short_name TEXT NOT NULL,
        kind TEXT NOT NULL,
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
    )
    """)
    # Schema migration for existing DB
    try:
        c.execute("ALTER TABLE symbols ADD COLUMN short_name TEXT")
        c.execute("UPDATE symbols SET short_name = name WHERE short_name IS NULL")
    except sqlite3.OperationalError:
        pass
    # 3. Edges Table - UNIQUE constraint prevents duplicate edges
    c.execute("""
    CREATE TABLE IF NOT EXISTS edges (
        source_id INTEGER NOT NULL,
        target_name TEXT NOT NULL,
        edge_type TEXT NOT NULL,
        UNIQUE(source_id, target_name, edge_type),
        FOREIGN KEY (source_id) REFERENCES symbols(id) ON DELETE CASCADE
    )
    """)
    # Indexes to prevent bottleneck during in-memory graph construction
    c.execute("CREATE INDEX IF NOT EXISTS idx_files_path ON files(file_path)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_symbols_short_name ON symbols(short_name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_name)")
    # Central SQL VIEW: resolves cross-file edges (DRY approach for graph_engine + export)
    c.execute("DROP VIEW IF EXISTS resolved_edges")
    c.execute("""
    CREATE VIEW IF NOT EXISTS resolved_edges AS
        SELECT e.source_id, s.id AS target_id, e.edge_type
        FROM edges e
        INNER JOIN symbols s ON (
            e.target_name = s.short_name 
            OR (s.kind = 'module' AND s.short_name = '<module: ' || e.target_name || '.py>')
            OR (
                e.edge_type = 'call'
                AND INSTR(e.target_name, '.') > 0
                AND (s.name LIKE '%::' || e.target_name OR s.name LIKE '%.' || e.target_name)
            )
        )
        INNER JOIN symbols src ON e.source_id = src.id
        INNER JOIN files target_file ON s.file_id = target_file.id
        WHERE s.file_id = src.file_id
           OR e.edge_type IN ('import', 'extends')
           OR EXISTS (
               SELECT 1 FROM edges e_imp
               INNER JOIN symbols s_mod ON e_imp.source_id = s_mod.id
               WHERE s_mod.file_id = src.file_id
                 AND e_imp.edge_type = 'import'
                 AND (
                     e_imp.target_name = e.target_name
                     OR (
                         INSTR(e.target_name, '.') > 0
                         AND e_imp.target_name = SUBSTR(e.target_name, 1, INSTR(e.target_name, '.') - 1)
                     )
                     OR target_file.file_path LIKE '%' || REPLACE(e_imp.target_name, '.', '/') || '%'
                 )
           )
    """)
    conn.commit()
    return conn

# Initialize Tree-sitter Parser
PY_LANGUAGE = Language(tspython.language())
parser = Parser(PY_LANGUAGE)

# Query: function, class, inheritance, calls, imports
QUERY_SCM = """
(function_definition name: (identifier) @symbol.function)
(class_definition name: (identifier) @symbol.class)
(class_definition superclasses: (argument_list (identifier) @edge.extends))
(call function: (identifier) @edge.call)
(call function: (attribute attribute: (identifier) @edge.call))
(import_statement name: (dotted_name) @edge.import)
(import_from_statement name: (dotted_name) @edge.import)
"""
query = Query(PY_LANGUAGE, QUERY_SCM)

def compute_checksum(source_code: bytes) -> str:
    return hashlib.md5(source_code).hexdigest()

def get_fqn(node, source_code: bytes, module_name: str = "") -> str:
    """Traverse up the AST to build Fully Qualified Name (e.g., ClassName.method_name)."""
    parts = []
    curr = node.parent
    while curr is not None:
        if curr.type in ('function_definition', 'class_definition'):
            for child in curr.children:
                if child.type == 'identifier':
                    parts.append(source_code[child.start_byte:child.end_byte].decode('utf8'))
                    break
        curr = curr.parent
    fqn = ".".join(reversed(parts)) if parts else source_code[node.start_byte:node.end_byte].decode('utf8')
    return f"{module_name}::{fqn}" if module_name else fqn

def find_enclosing_symbol(node, source_code: bytes, module_name: str) -> str:
    """
    Traverse up the AST to find the FQN of the enclosing function/class.
    """
    curr = node.parent
    while curr is not None:
        if curr.type in ('function_definition', 'class_definition'):
            for child in curr.children:
                if child.type == 'identifier':
                    return get_fqn(child, source_code, module_name)
        curr = curr.parent
    return module_name

def _node_text(node, source_code: bytes) -> str:
    return source_code[node.start_byte:node.end_byte].decode('utf8')

def find_enclosing_class_short_name(node, source_code: bytes) -> str | None:
    """Return the short class name enclosing this node, if any."""
    curr = node.parent
    while curr is not None:
        if curr.type == 'class_definition':
            for child in curr.children:
                if child.type == 'identifier':
                    return _node_text(child, source_code)
            return None
        curr = curr.parent
    return None

def _extract_lhs_var_name(left_node, source_code: bytes) -> str | None:
    if left_node is None:
        return None
    if left_node.type == 'identifier':
        return _node_text(left_node, source_code)
    return None

def _extract_call_constructor_name(call_node, source_code: bytes) -> str | None:
    """Extract class name from `ClassName(...)` or `module.ClassName(...)`."""
    func = call_node.child_by_field_name('function')
    if func is None:
        return None
    if func.type == 'identifier':
        return _node_text(func, source_code)
    if func.type == 'attribute':
        attr = func.child_by_field_name('attribute')
        if attr is not None:
            return _node_text(attr, source_code)
    return None

def build_variable_type_maps(root_node, source_code: bytes, module_name: str) -> dict[str, dict[str, str]]:
    """
    Pass 0: assignment-based heuristic — map variable names to constructor class
    names within each enclosing scope. Example: session = Session() in func f
    yields maps['<module: foo.py>::f']['session'] = 'Session'.
    """
    scope_maps: dict[str, dict[str, str]] = {}

    def visit(node):
        if node.type in ('assignment', 'annotated_assignment'):
            left = node.child_by_field_name('left')
            right = node.child_by_field_name('right')
            if left is not None and right is not None and right.type == 'call':
                var_name = _extract_lhs_var_name(left, source_code)
                class_name = _extract_call_constructor_name(right, source_code)
                if var_name and class_name:
                    scope = find_enclosing_symbol(node, source_code, module_name)
                    scope_maps.setdefault(scope, {})[var_name] = class_name
        for child in node.children:
            visit(child)

    visit(root_node)
    return scope_maps

ROUTE_DECORATOR_METHODS = frozenset({
    'route', 'get', 'post', 'put', 'delete', 'patch', 'head', 'options',
    'trace', 'websocket', 'api_route', 'add_url_rule',
})

def _strip_python_string(text: str) -> str:
    if len(text) >= 2 and text[0] in ('"', "'") and text[-1] == text[0]:
        return text[1:-1]
    return text

def _first_string_literal_in_args(call_node, source_code: bytes) -> str | None:
    args = call_node.child_by_field_name('arguments')
    if args is None:
        return None
    for child in args.children:
        if child.type == 'string':
            return _strip_python_string(_node_text(child, source_code))
        if child.type == 'concatenated_string':
            for part in child.children:
                if part.type == 'string':
                    return _strip_python_string(_node_text(part, source_code))
    return None

def _decorator_http_method(call_node, source_code: bytes) -> str | None:
    func = call_node.child_by_field_name('function')
    if func is None or func.type != 'attribute':
        return None
    attr = func.child_by_field_name('attribute')
    return _node_text(attr, source_code) if attr is not None else None

def _format_route_short_name(method: str, path: str) -> str:
    if method == 'route':
        return f"route:{path}"
    return f"{method.upper()} {path}"

def _decorator_call_from_node(decorator_node) -> object | None:
    for child in decorator_node.children:
        if child.type == 'call':
            return child
    return None

def index_route_decorators(
    root_node,
    source_code: bytes,
    module_name: str,
    symbol_map: dict,
    file_id: int,
    module_id: int,
    cursor,
) -> None:
    """
    Detect Flask/FastAPI-style route decorators and wire semantic edges:
      route:/users --handles--> get_users
      GET /items   --handles--> list_items
    """
    route_symbol_ids: dict[str, int] = {}

    def _wire_route_decorators(decorator_nodes, func_node) -> None:
        name_node = func_node.child_by_field_name('name')
        if name_node is None:
            return
        handler_short = _node_text(name_node, source_code)
        handler_fqn = get_fqn(name_node, source_code, module_name)
        if handler_fqn not in symbol_map:
            return

        start_line = getattr(func_node.start_point, 'row', None)
        if start_line is None:
            start_line = func_node.start_point[0]
        end_line = getattr(func_node.end_point, 'row', None)
        if end_line is None:
            end_line = func_node.end_point[0]

        for decorator_node in decorator_nodes:
            call_expr = _decorator_call_from_node(decorator_node)
            if call_expr is None:
                continue
            method = _decorator_http_method(call_expr, source_code)
            if method not in ROUTE_DECORATOR_METHODS:
                continue
            path = _first_string_literal_in_args(call_expr, source_code)
            if not path:
                continue

            route_short = _format_route_short_name(method, path)
            route_fqn = f"{module_name}::{route_short}"
            if route_short not in route_symbol_ids:
                cursor.execute(
                    "INSERT INTO symbols (file_id, name, short_name, kind, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?)",
                    (file_id, route_fqn, route_short, 'route', start_line, end_line),
                )
                route_id = cursor.lastrowid
                route_symbol_ids[route_short] = route_id
                symbol_map[route_fqn] = route_id
                logging.info(f"  [+] Node: Route '{route_fqn}' (ID: {route_id})")
                cursor.execute(
                    "INSERT OR IGNORE INTO edges (source_id, target_name, edge_type) VALUES (?, ?, ?)",
                    (module_id, route_short, 'contains'),
                )
                logging.info(f"  [->] Edge: '{module_name}' contains route '{route_fqn}'")

            route_id = route_symbol_ids[route_short]
            cursor.execute(
                "INSERT OR IGNORE INTO edges (source_id, target_name, edge_type) VALUES (?, ?, ?)",
                (route_id, handler_short, 'handles'),
            )
            logging.info(f"  [->] Edge: '{route_fqn}' --[handles]--> '{handler_short}'")

    def visit(node):
        if node.type == 'decorated_definition':
            decorator_nodes = [child for child in node.children if child.type == 'decorator']
            func_node = next((child for child in node.children if child.type == 'function_definition'), None)
            if func_node is not None and decorator_nodes:
                _wire_route_decorators(decorator_nodes, func_node)
        elif node.type == 'function_definition':
            decorator_nodes = []
            for child in node.children:
                if child.type == 'decorator':
                    decorator_nodes.append(child)
                elif child.type == 'def':
                    break
            if decorator_nodes:
                _wire_route_decorators(decorator_nodes, node)

        for child in node.children:
            visit(child)

    visit(root_node)

def resolve_call_target(
    node,
    source_code: bytes,
    module_name: str,
    var_type_maps: dict[str, dict[str, str]],
) -> str:
    """
    Resolve a call edge target using assignment-based and self/cls heuristics.
    Falls back to the bare method/function name when type is unknown.
    """
    parent = node.parent
    if parent is not None and parent.type == 'attribute':
        method_name = _node_text(node, source_code)
        obj_node = parent.child_by_field_name('object')
        if obj_node is None:
            return method_name

        obj_name = _node_text(obj_node, source_code)
        if obj_name in ('self', 'cls'):
            class_name = find_enclosing_class_short_name(node, source_code)
            if class_name:
                return f"{class_name}.{method_name}"
            return method_name

        scope = find_enclosing_symbol(node, source_code, module_name)
        resolved_class = var_type_maps.get(scope, {}).get(obj_name)
        if resolved_class:
            return f"{resolved_class}.{method_name}"
        return method_name

    target_name = _node_text(node, source_code)
    if '.' in target_name:
        return target_name.split('.')[-1]
    return target_name

def parse_python_file(file_path, conn):
    try:
        with open(file_path, "rb") as f:
            source_code = f.read()
    except Exception as e:
        logging.info(f"❌ [I/O ERROR] Skipping file '{file_path}': {e}")
        return
        
    checksum = compute_checksum(source_code)
    cursor = conn.cursor()
    
    # 1. Incremental Parsing Mechanism
    try:
        cursor.execute("SELECT id, checksum FROM files WHERE file_path = ?", (file_path,))
    except sqlite3.OperationalError as e:
        logging.info(f"❌ [DB ERROR] Database not initialized properly: {e}")
        return

    row = cursor.fetchone()
    if row:
        file_id, old_checksum = row
        if old_checksum == checksum:
            logging.info(f"[SKIP] '{file_path}' has no changes (Checksum matches).")
            return
        else:
            logging.info(f"[UPDATE] '{file_path}' has changed. Re-parsing...")
            # Cascade delete symbols (cascades to edges)
            cursor.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
            cursor.execute("UPDATE files SET checksum = ?, last_parsed = CURRENT_TIMESTAMP WHERE id = ?", (checksum, file_id))
    else:
        logging.info(f"[NEW] Parsing '{file_path}'...")
        cursor.execute("INSERT INTO files (file_path, checksum) VALUES (?, ?)", (file_path, checksum))
        file_id = cursor.lastrowid
        
    # 2. Parse source code into AST
    tree = parser.parse(source_code)
    qc = QueryCursor(query)
    captures = qc.captures(tree.root_node)
    
    # Standardize capture API for different tree-sitter versions
    if isinstance(captures, dict):
        capture_items = [(node, name) for name, nodes in captures.items() for node in nodes]
    else:
        capture_items = captures

    symbol_map = {}
    
    # Register Module node representing the file
    module_name = f"<module: {os.path.basename(file_path)}>"
    cursor.execute(
        "INSERT INTO symbols (file_id, name, short_name, kind, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?)",
        (file_id, module_name, module_name, "module", 0, 0)
    )
    symbol_map[module_name] = cursor.lastrowid
    logging.info(f"  [+] Node: Module '{module_name}'")
    
    # 3. First Pass: Store all Symbols (Nodes)
    for node, capture_name in capture_items:
        if capture_name in ('symbol.function', 'symbol.class'):
            short_name = source_code[node.start_byte:node.end_byte].decode('utf8')
            name = get_fqn(node, source_code, module_name)
            kind = capture_name.split('.')[1]
            
            # Use block node (parent) instead of the bare identifier node to capture full coordinates
            block_node = node.parent if node.parent else node
            
            # API compatibility for Point coordinates
            start_line = getattr(block_node.start_point, 'row', None)
            if start_line is None: start_line = block_node.start_point[0]
            end_line = getattr(block_node.end_point, 'row', None)
            if end_line is None: end_line = block_node.end_point[0]

            # Deduplicate by FQN. Real code legitimately declares the same FQN more
            # than once: `typing.@overload` stubs (the dominant case) plus
            # property getter/setter pairs. Each extra declaration would otherwise
            # create a phantom duplicate node and pollute the graph. We keep ONE
            # node per FQN, preferring the definition with the largest body (the
            # concrete implementation, not the `...` overload stub).
            if name in symbol_map:
                existing_id = symbol_map[name]
                cursor.execute("SELECT start_line, end_line FROM symbols WHERE id = ?", (existing_id,))
                prev = cursor.fetchone()
                if prev and (end_line - start_line) > (prev[1] - prev[0]):
                    cursor.execute(
                        "UPDATE symbols SET kind = ?, start_line = ?, end_line = ? WHERE id = ?",
                        (kind, start_line, end_line, existing_id)
                    )
                logging.info(f"  [=] Dedup: '{name}' already defined (overload/getter-setter), keeping largest body.")
                continue

            cursor.execute(
                "INSERT INTO symbols (file_id, name, short_name, kind, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?)",
                (file_id, name, short_name, kind, start_line, end_line)
            )
            symbol_id = cursor.lastrowid
            symbol_map[name] = symbol_id
            logging.info(f"  [+] Node: {kind.capitalize()} '{name}' (ID: {symbol_id}, Lines: {start_line}-{end_line})")
            
            # Add a containment edge linking this symbol to its enclosing scope.
            # Applies to BOTH functions and classes so every top-level symbol stays
            # attached to its module node (otherwise class-only files float as
            # isolated/standalone modules in the graph). Nested symbols attach to
            # their enclosing class/function instead.
            parent_name = find_enclosing_symbol(block_node, source_code, module_name)
            parent_id = symbol_map.get(parent_name)
            if parent_id and parent_id != symbol_id:
                # OR IGNORE: real codebases legitimately repeat a short_name inside
                # one scope (e.g. multiple decorator `wrapper` functions, property
                # getter/setter pairs), which would otherwise trip the UNIQUE
                # (source_id, target_name, edge_type) constraint and abort indexing.
                cursor.execute(
                    "INSERT OR IGNORE INTO edges (source_id, target_name, edge_type) VALUES (?, ?, ?)",
                    (parent_id, short_name, 'contains')
                )
                logging.info(f"  [->] Edge: '{parent_name}' contains {kind} '{name}'")

    BUILTIN_IGNORE = {'print', 'len', 'range', 'str', 'int', 'list', 'dict', 'isinstance', 'type', 'super', 'enumerate', 'zip'}

    var_type_maps = build_variable_type_maps(tree.root_node, source_code, module_name)

    # 4. Second Pass: Store all Edges (call, import, extends) with Context Tracking
    for node, capture_name in capture_items:
        if capture_name in ('edge.call', 'edge.import', 'edge.extends'):
            if capture_name == 'edge.call':
                target_name = resolve_call_target(node, source_code, module_name, var_type_maps)
            else:
                target_name = _node_text(node, source_code)
                if '.' in target_name:
                    target_name = target_name.split('.')[-1]

            edge_type = capture_name.split('.')[1]  # 'call', 'import', or 'extends'
            
            # Filter out standard builtin functions
            if edge_type == 'call' and target_name in BUILTIN_IGNORE:
                continue
            
            # Trace enclosing parent context
            caller_name = find_enclosing_symbol(node, source_code, module_name)
            source_id = symbol_map.get(caller_name)
            
            if source_id:
                # INSERT OR IGNORE avoids duplicates due to SQL unique constraints
                cursor.execute(
                    "INSERT OR IGNORE INTO edges (source_id, target_name, edge_type) VALUES (?, ?, ?)",
                    (source_id, target_name, edge_type)
                )
                logging.info(f"  [->] Edge: '{caller_name}' --[{edge_type}]--> '{target_name}'")

    index_route_decorators(
        tree.root_node,
        source_code,
        module_name,
        symbol_map,
        file_id,
        symbol_map[module_name],
        cursor,
    )

    conn.commit()
    logging.info(f"✅ Successfully saved '{file_path}' to SQLite!\n")

import argparse

def scan_directory(directory_path, conn):
    logging.info(f"🔍 Scanning directory: {directory_path}")
    py_files_count = 0
    for root, _, files in os.walk(directory_path):
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                parse_python_file(file_path, conn)
                py_files_count += 1
    
    logging.info(f"\n✅ Finished scanning {py_files_count} Python files in the codebase.")

def main():
    cli_parser = argparse.ArgumentParser(description="Codebase Knowledge Graph Indexer")
    cli_parser.add_argument("target_path", nargs="?", default="sample_app.py", help="Target path to index (default: sample_app.py)")
    cli_parser.add_argument("--db", default="graphrag_code.sqlite", help="Path to SQLite database (default: graphrag_code.sqlite)")
    args = cli_parser.parse_args()

    logging.info(f"Initializing database: {args.db}")
    conn = init_db(args.db)
    
    target_path = args.target_path
    if not os.path.exists(target_path):
        logging.info(f"❌ Error: Path '{target_path}' not found.")
    else:
        if os.path.isdir(target_path):
            scan_directory(target_path, conn)
        else:
            parse_python_file(target_path, conn)
    
    conn.close()

if __name__ == "__main__":
    main()
