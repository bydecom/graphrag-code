import unittest
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from graphrag_code.graph_engine import GraphRAGCodeEngine, IMPACT_BACKWARD_WEIGHT
from test_graph_engine_extended import build_mock_db
import eval_retrieval as ev


class TestEvalRetrieval(unittest.TestCase):
    """Smoke tests for the RQ1 structural-retrieval harness."""

    def setUp(self):
        self.db_path = "test_eval_rq1.sqlite"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        build_mock_db(self.db_path)
        self.engine = GraphRAGCodeEngine(self.db_path)
        self.engine.load_graph()
        self.seed_idx = self.engine.get_node_index("ProcessPayment")

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_blast_radius_ground_truth_includes_caller(self):
        """ApiGateway calls ProcessPayment, so it is in the blast-radius closure."""
        gt = ev.ground_truth(self.engine, self.seed_idx, "blast_radius")
        self.assertIn("ApiGateway", gt)

    def test_dependencies_ground_truth_includes_callees(self):
        """ProcessPayment calls StripeAPI and Logger (downstream closure)."""
        gt = ev.ground_truth(self.engine, self.seed_idx, "dependencies")
        self.assertIn("StripeAPI", gt)
        self.assertIn("Logger", gt)

    def test_metrics_are_bounded(self):
        """recall/precision must stay within [0, 1] even with duplicate names."""
        relevant = {"A", "B", "C"}
        retrieved = ["A", "A", "B", "X"]  # duplicate 'A' must not double-count
        self.assertLessEqual(ev.recall_at_k(retrieved, relevant, 4), 1.0)
        self.assertAlmostEqual(ev.recall_at_k(retrieved, relevant, 4), 2 / 3)
        self.assertLessEqual(ev.precision_at_k(retrieved, relevant, 4), 1.0)

    def test_bidirectional_beats_unidirectional_on_blast_radius(self):
        """Core RQ1 claim: forward-only fails upstream; bidirectional recovers it."""
        seed_name = "ProcessPayment"
        relevant = ev.ground_truth(self.engine, self.seed_idx, "blast_radius")

        uni = ev.uni_directional_arm(self.engine, seed_name, top_k=5)
        bi = ev.bi_directional_arm(self.engine, seed_name, top_k=5,
                                   backward_weight=IMPACT_BACKWARD_WEIGHT)

        uni_recall = ev.recall_at_k(uni, relevant, 5)
        bi_recall = ev.recall_at_k(bi, relevant, 5)
        self.assertGreaterEqual(bi_recall, uni_recall)
        # The upstream caller surfaces only in the bidirectional arm.
        self.assertIn("ApiGateway", bi)
        self.assertNotIn("ApiGateway", uni)

    def test_evaluate_cases_held_out(self):
        """Held-out cases evaluator returns per-arm recall for each named seed."""
        cases = [
            {"seed": "ProcessPayment", "task": "blast_radius", "note": "hub"},
            {"seed": "ProcessPayment", "task": "dependencies"},
        ]
        report = ev.evaluate_cases(self.engine, cases, [3, 5])
        self.assertEqual(report["mode"], "held_out_cases")
        self.assertEqual(len(report["cases"]), 2)
        for row in report["cases"]:
            self.assertNotIn("error", row)
            for arm in ev.ARMS:
                self.assertIn("recall@5", row["metrics"][arm])
                self.assertLessEqual(row["metrics"][arm]["recall@5"], 1.0)

    def test_evaluate_cases_unknown_seed_marked(self):
        """An unresolved seed is reported as an error, not a crash."""
        report = ev.evaluate_cases(self.engine, [{"seed": "Nope_ZZZ", "task": "blast_radius"}], [5])
        self.assertIn("error", report["cases"][0])

    def test_evaluate_task_smoke(self):
        """End-to-end driver returns a well-formed summary for all arms."""
        seeds = ev.auto_select_seeds(self.engine, "blast_radius", num_seeds=5)
        report = ev.evaluate_task(self.engine, "blast_radius", seeds, [3, 5])
        self.assertEqual(report["task"], "blast_radius")
        for arm in ev.ARMS:
            self.assertIn("recall@3", report["summary"][arm])
            self.assertLessEqual(report["summary"][arm]["recall@5"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
