import unittest
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from graphrag_code.graph_engine import GraphRAGCodeEngine
from graphrag_code import mcp_server
from test_graph_engine_extended import build_mock_db


class TestPlanChange(unittest.TestCase):
    """Format/contract tests for the plan_change MCP tool (metadata-first)."""

    def setUp(self):
        self.db_path = "test_mcp_plan.sqlite"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        build_mock_db(self.db_path)
        engine = GraphRAGCodeEngine(self.db_path)
        engine.load_graph()
        # Inject our loaded engine into the module-level global the tools use.
        self._saved_engine = mcp_server.engine
        mcp_server.engine = engine

    def tearDown(self):
        mcp_server.engine = self._saved_engine
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_known_symbol_returns_plan(self):
        """A valid symbol produces a Change Plan with a risk header."""
        out = mcp_server.plan_change("ProcessPayment")
        self.assertIn("Change Plan for `ProcessPayment`", out)
        self.assertIn("Overall Risk:", out)
        self.assertIn("Blast Radius", out)
        self.assertIn("Dependencies", out)

    def test_metadata_only_by_default(self):
        """Default call must NOT embed source code (token-light)."""
        out = mcp_server.plan_change("ProcessPayment")
        self.assertNotIn("```python", out)

    def test_include_snippets_adds_source(self):
        """include_snippets=True appends the seed's source block."""
        out = mcp_server.plan_change("ProcessPayment", include_snippets=True)
        self.assertIn("```python", out)
        self.assertIn("Source", out)
        self.assertIn("**File:**", out)

    def test_ambiguous_symbol_triggers_disambiguation(self):
        """'validate' (2 files) must return the disambiguation prompt, not a plan."""
        out = mcp_server.plan_change("validate")
        self.assertIn("Ambiguous symbol", out)
        self.assertNotIn("Overall Risk:", out)

    def test_unknown_symbol_reports_not_found(self):
        """Unknown symbol returns a not-found message."""
        out = mcp_server.plan_change("NoSuchSymbol_ZZZ")
        self.assertIn("not found", out.lower())

    def test_affected_files_section_present(self):
        """The factual affected-files aggregation is always rendered."""
        out = mcp_server.plan_change("ProcessPayment")
        self.assertIn("Affected Files", out)

    def test_risk_header_reflects_direct_caller_count(self):
        """ProcessPayment has exactly 1 direct caller (ApiGateway) ? LOW risk."""
        out = mcp_server.plan_change("ProcessPayment")
        self.assertIn("1 direct caller(s)", out)
        self.assertIn("LOW", out)
        self.assertNotIn("HIGH", out)

    def test_direct_callers_section_lists_caller(self):
        """The Direct Callers section names the depth-1 caller explicitly."""
        out = mcp_server.plan_change("ProcessPayment")
        self.assertIn("Direct Callers", out)
        self.assertIn("ApiGateway", out)

    def test_affected_files_includes_direct_caller_file(self):
        """A direct caller's file must appear even with a tiny top_k_upstream."""
        out = mcp_server.plan_change("ProcessPayment", top_k_upstream=1)
        # gateway.py hosts ApiGateway (the direct caller) and must not be dropped.
        self.assertIn("gateway.py", out)

    def test_no_fabricated_recommendation(self):
        """Tool must not emit LLM-style advice like 'run the test suite'."""
        out = mcp_server.plan_change("ProcessPayment").lower()
        self.assertNotIn("run the test", out)
        self.assertNotIn("you should", out)


class TestRiskHelper(unittest.TestCase):
    """Risk thresholds derive solely from direct caller count."""

    def test_low_risk(self):
        self.assertIn("LOW", mcp_server._change_risk(0))
        self.assertIn("LOW", mcp_server._change_risk(5))

    def test_medium_risk(self):
        self.assertIn("MEDIUM", mcp_server._change_risk(6))
        self.assertIn("MEDIUM", mcp_server._change_risk(20))

    def test_high_risk(self):
        self.assertIn("HIGH", mcp_server._change_risk(21))
        self.assertIn("HIGH", mcp_server._change_risk(100))


if __name__ == "__main__":
    unittest.main(verbosity=2)
