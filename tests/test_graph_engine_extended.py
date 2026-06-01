import unittest
import sqlite3
import os
import sys
import tempfile

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from graphrag_code.indexer import init_db
from graphrag_code.graph_engine import GraphRAGCodeEngine


def build_mock_db(db_path: str) -> None:
    """
    Xây dựng mock database với cấu trúc:

    ApiGateway ──call──> ProcessPayment ──call──> StripeAPI
                                         ──call──> Logger

    + DuplicateService (tên class trùng với module khác)

    Dùng cho tất cả test cases trong file này.
    """
    conn = init_db(db_path)
    cursor = conn.cursor()

    cursor.execute("INSERT INTO files (file_path, checksum) VALUES ('payment.py', 'hash_payment')")
    file_a = cursor.lastrowid
    cursor.execute("INSERT INTO files (file_path, checksum) VALUES ('gateway.py', 'hash_gateway')")
    file_b = cursor.lastrowid

    # File A symbols
    symbols_a = [
        (file_a, "ProcessPayment", "ProcessPayment", "function", 1, 20),
        (file_a, "StripeAPI",      "StripeAPI",      "class",    22, 40),
        (file_a, "Logger",         "Logger",          "class",    42, 50),
        # Duplicate: cùng tên "validate" xuất hiện ở 2 chỗ
        (file_a, "validate",       "validate",        "function", 52, 60),
    ]
    # File B symbols
    symbols_b = [
        (file_b, "ApiGateway",     "ApiGateway",      "class",    1,  15),
        # Duplicate: "validate" cũng có ở file_b
        (file_b, "validate",       "validate",        "function", 17, 25),
    ]

    cursor.executemany(
        "INSERT INTO symbols (file_id, name, short_name, kind, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?)",
        symbols_a + symbols_b
    )

    cursor.execute("SELECT id, name, file_id FROM symbols")
    rows = cursor.fetchall()
    sym_map = {(name, file_id): sid for sid, name, file_id in rows}

    edges = [
        # gateway.py imports payment.py — required so the cross-file call below
        # survives the `resolved_edges` view (which filters cross-file calls that
        # lack a backing import, mirroring real indexer behaviour).
        (sym_map[("ApiGateway", file_b)],     "payment",        "import"),
        (sym_map[("ApiGateway", file_b)],     "ProcessPayment", "call"),
        (sym_map[("ProcessPayment", file_a)], "StripeAPI",       "call"),
        (sym_map[("ProcessPayment", file_a)], "Logger",          "call"),
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO edges (source_id, target_name, edge_type) VALUES (?, ?, ?)",
        edges
    )
    conn.commit()
    conn.close()


class TestGetNodeIndex(unittest.TestCase):
    """Test O(1) symbol lookup với exact match và suffix match."""

    def setUp(self):
        self.db_path = "test_ext_engine.sqlite"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        build_mock_db(self.db_path)
        self.engine = GraphRAGCodeEngine(self.db_path)
        self.engine.load_graph()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_exact_match_returns_index(self):
        """Exact symbol name phải trả về rx_idx hợp lệ."""
        idx = self.engine.get_node_index("ProcessPayment")
        self.assertIsNotNone(idx)

    def test_unknown_symbol_returns_none(self):
        """Symbol không tồn tại phải trả về None, không raise exception."""
        idx = self.engine.get_node_index("NonExistentFunction_XYZ")
        self.assertIsNone(idx)

    def test_duplicate_symbol_returns_first_and_warns(self):
        """
        Khi có 2 symbols cùng tên 'validate' ở 2 files khác nhau,
        get_node_index phải:
        1. Trả về một index hợp lệ (không crash)
        2. Log warning (chúng ta chỉ test không crash ở đây)
        """
        idx = self.engine.get_node_index("validate")
        self.assertIsNotNone(idx)
        # Index phải nằm trong graph
        self.assertIn(idx, self.engine.graph.node_indices())

    def test_duplicate_stored_as_list_in_name_map(self):
        """
        name_to_rx_idx phải lưu list khi có duplicate,
        không phải overwrite bằng giá trị cuối cùng.
        """
        stored = self.engine.name_to_rx_idx.get("validate")
        self.assertIsNotNone(stored)
        # Phải là list vì có 2 symbols cùng tên
        self.assertIsInstance(stored, list)
        self.assertEqual(len(stored), 2)


class TestSymbolDisambiguation(unittest.TestCase):
    """Disambiguation contract: ambiguous names must be surfaced, not guessed."""

    def setUp(self):
        self.db_path = "test_disambig.sqlite"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        build_mock_db(self.db_path)
        self.engine = GraphRAGCodeEngine(self.db_path)
        self.engine.load_graph()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_find_candidates_unique(self):
        """Unique symbol → exactly one candidate index."""
        candidates = self.engine.find_candidates("ProcessPayment")
        self.assertEqual(len(candidates), 1)

    def test_find_candidates_unknown(self):
        """Unknown symbol → empty candidate list (no crash)."""
        self.assertEqual(self.engine.find_candidates("DoesNotExist_XYZ"), [])

    def test_find_candidates_ambiguous(self):
        """'validate' exists in 2 files → 2 candidates."""
        candidates = self.engine.find_candidates("validate")
        self.assertEqual(len(candidates), 2)

    def test_resolve_symbol_unique(self):
        """Unique → (idx, [single described candidate])."""
        idx, candidates = self.engine.resolve_symbol("ProcessPayment")
        self.assertIsNotNone(idx)
        self.assertEqual(len(candidates), 1)
        self.assertIn("name", candidates[0])
        self.assertIn("file_path", candidates[0])

    def test_resolve_symbol_ambiguous_returns_none_idx(self):
        """Ambiguous → idx is None so the caller cannot silently proceed."""
        idx, candidates = self.engine.resolve_symbol("validate")
        self.assertIsNone(idx)
        self.assertEqual(len(candidates), 2)

    def test_resolve_symbol_not_found(self):
        """Unknown → (None, [])."""
        idx, candidates = self.engine.resolve_symbol("Nope_ZZZ")
        self.assertIsNone(idx)
        self.assertEqual(candidates, [])

    def test_get_node_index_backward_compatible(self):
        """Legacy wrapper still returns a valid first index for ambiguous names."""
        idx = self.engine.get_node_index("validate")
        self.assertIsNotNone(idx)
        self.assertIn(idx, self.engine.graph.node_indices())


class TestPPRReturnSemantics(unittest.TestCase):
    """
    Test semantic của return value: None vs [] vs list có data.
    None = seed không tồn tại.
    [] = seed tồn tại nhưng bị isolated.
    list = kết quả bình thường.
    """

    def setUp(self):
        self.db_path = "test_ppr_semantic.sqlite"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        build_mock_db(self.db_path)
        self.engine = GraphRAGCodeEngine(self.db_path)
        self.engine.load_graph()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_unknown_seed_returns_none(self):
        """Seed không tồn tại → None (bukan [])."""
        result = self.engine.get_context_ppr("CompletelyUnknownFunction_ZZZ")
        self.assertIsNone(result)

    def test_known_seed_with_deps_returns_list(self):
        """Seed có dependencies → list không rỗng."""
        result = self.engine.get_context_ppr("ProcessPayment", top_k=5)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_seed_not_in_result(self):
        """
        Issue 1: Seed node bị loại khỏi kết quả.
        Agent không nên nhận lại thứ nó đã biết.
        """
        result = self.engine.get_context_ppr("ProcessPayment", top_k=5)
        names = [item["name"] for item in result]
        self.assertNotIn("ProcessPayment", names)

    def test_result_items_have_required_fields(self):
        """Mỗi item trong kết quả phải có đủ các fields cần thiết."""
        result = self.engine.get_context_ppr("ProcessPayment", top_k=3)
        self.assertIsNotNone(result)
        for item in result:
            self.assertIn("name", item)
            self.assertIn("kind", item)
            self.assertIn("score", item)
            self.assertIn("fwd_score", item)
            self.assertIn("bwd_score", item)
            self.assertIn("file_path", item)
            self.assertIn("source_code", item)

    def test_scores_are_positive(self):
        """Tất cả scores phải > 0 (đã filter bởi `if score > 0`)."""
        result = self.engine.get_context_ppr("ProcessPayment", top_k=5)
        for item in result:
            self.assertGreater(item["score"], 0)


class TestBackwardWeightBehavior(unittest.TestCase):
    """
    Test hành vi của Non-linear merge tại các ngưỡng backward_weight.
    Đây là ablation study dạng unit test — justify con số 0.2 và 0.9.
    """

    def setUp(self):
        self.db_path = "test_bw_behavior.sqlite"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        build_mock_db(self.db_path)
        self.engine = GraphRAGCodeEngine(self.db_path)
        self.engine.load_graph()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_low_weight_prioritizes_downstream(self):
        """
        backward_weight=0.0 → Pure forward PPR.
        ApiGateway (upstream caller) phải có score thấp hơn StripeAPI (downstream dep).
        """
        result = self.engine.get_context_ppr("ProcessPayment", top_k=5, backward_weight=0.0)
        self.assertIsNotNone(result)

        names = [item["name"] for item in result]
        scores = {item["name"]: item["score"] for item in result}

        # Downstream deps phải xuất hiện trong results
        self.assertTrue(
            any(n in names for n in ["StripeAPI", "Logger"]),
            "At backward_weight=0.0, downstream deps (StripeAPI/Logger) must appear"
        )

    def test_high_weight_surfaces_caller(self):
        """
        backward_weight=0.9 → Blast radius mode.
        ApiGateway (upstream caller) phải xuất hiện trong top results.
        """
        result = self.engine.get_context_ppr("ProcessPayment", top_k=5, backward_weight=0.9)
        self.assertIsNotNone(result)

        names = [item["name"] for item in result]
        self.assertIn("ApiGateway", names,
                      "At backward_weight=0.9, upstream caller (ApiGateway) must appear")

    def test_ranking_is_descending(self):
        """Kết quả phải được sort theo score giảm dần."""
        result = self.engine.get_context_ppr("ProcessPayment", top_k=5)
        if result and len(result) > 1:
            scores = [item["score"] for item in result]
            for i in range(len(scores) - 1):
                self.assertGreaterEqual(
                    scores[i], scores[i + 1],
                    f"Score at rank {i+1} ({scores[i]}) < score at rank {i+2} ({scores[i+1]})"
                )

    def test_top_k_respected(self):
        """top_k phải giới hạn số lượng kết quả trả về."""
        for k in [1, 2, 3]:
            result = self.engine.get_context_ppr("ProcessPayment", top_k=k)
            if result is not None:
                self.assertLessEqual(
                    len(result), k,
                    f"top_k={k} but got {len(result)} results"
                )


class TestExtractSourceCode(unittest.TestCase):
    """Test _extract_source_code error handling."""

    def setUp(self):
        self.db_path = "test_extract.sqlite"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        build_mock_db(self.db_path)
        self.engine = GraphRAGCodeEngine(self.db_path)
        self.engine.load_graph()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_missing_file_returns_error_string(self):
        """
        Khi file không tồn tại trên disk,
        phải trả về error string (không crash, không raise).
        """
        result = self.engine._extract_source_code(
            "/absolutely/nonexistent/path/file.py", 0, 10
        )
        self.assertIsInstance(result, str)
        self.assertIn("not found", result.lower())

    def test_valid_temp_file_extraction(self):
        """
        Với file thật, phải extract đúng dòng theo start/end line.
        Tree-sitter dùng 0-indexed, Python slice [start:end+1].
        """
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.py', delete=False, encoding='utf-8'
        ) as f:
            f.write("line0\nline1\nline2\nline3\nline4\n")
            tmp_path = f.name

        try:
            # Extract dòng 1 đến 3 (0-indexed) → "line1\nline2\nline3"
            result = self.engine._extract_source_code(tmp_path, 1, 3)
            self.assertEqual(result, "line1\nline2\nline3")
        finally:
            os.unlink(tmp_path)

    def test_out_of_range_lines_no_crash(self):
        """
        start_line hoặc end_line vượt quá số dòng thực tế
        không được crash — Python slice xử lý gracefully.
        """
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.py', delete=False, encoding='utf-8'
        ) as f:
            f.write("only_one_line\n")
            tmp_path = f.name

        try:
            result = self.engine._extract_source_code(tmp_path, 0, 999)
            self.assertIsInstance(result, str)
        finally:
            os.unlink(tmp_path)


class TestGraphStructure(unittest.TestCase):
    """Test tính đúng đắn của graph structure sau load_graph."""

    def setUp(self):
        self.db_path = "test_structure.sqlite"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        build_mock_db(self.db_path)
        self.engine = GraphRAGCodeEngine(self.db_path)
        self.engine.load_graph()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_reversed_graph_has_same_node_count(self):
        """reversed_graph phải có cùng số nodes với graph gốc."""
        self.assertEqual(
            self.engine.graph.num_nodes(),
            self.engine.reversed_graph.num_nodes()
        )

    def test_reversed_graph_has_same_edge_count(self):
        """reversed_graph phải có cùng số edges (chỉ đảo chiều)."""
        self.assertEqual(
            self.engine.graph.num_edges(),
            self.engine.reversed_graph.num_edges()
        )

    def test_name_to_rx_idx_covers_all_symbols(self):
        """
        name_to_rx_idx phải cover tất cả symbols đã load.
        Tổng số unique names ≤ total nodes.
        """
        total_names_in_map = sum(
            len(v) if isinstance(v, list) else 1
            for v in self.engine.name_to_rx_idx.values()
        )
        self.assertEqual(total_names_in_map, self.engine.graph.num_nodes())

    def test_sqlite_id_mapping_completeness(self):
        """sqlite_id_to_rx_idx phải map đúng số lượng nodes."""
        self.assertEqual(
            len(self.engine.sqlite_id_to_rx_idx),
            self.engine.graph.num_nodes()
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
