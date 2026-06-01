"""
eval_retrieval.py - RQ1: Structural Retrieval Quality (offline, no LLM)
======================================================================
Answers Research Question 1: *Does Bidirectional PPR retrieve the
structurally-relevant symbols better than naive neighbour expansion or a
single-direction PageRank?*

This is a DETERMINISTIC evaluation - no LLM, no API key, no network. The ground
truth is derived directly from the dependency graph (transitive closure), so the
numbers are reproducible and cannot be gamed by prompt wording.

Three retrieval arms compete under a fixed budget `k`:

    1. brute_force_arm     - 1-hop neighbours only, ranked by node degree
                             (the "just grab what's directly connected" baseline).
    2. uni_directional_arm - forward-only Personalized PageRank
                             (ablation: proves why a single direction is not enough).
    3. bi_directional_arm  - the system: Bidirectional PPR via the REAL engine
                             (engine.get_context_ppr), so we measure what ships.

Two tasks (ground-truth directions):
    - blast_radius : relevant = all transitive CALLERS (upstream).  Bidirectional
                     (backward-leaning) should win; forward-only should fail.
    - dependencies : relevant = all transitive CALLEES (downstream). Forward PPR
                     is strong here; this keeps the comparison honest.

Metric: recall@k and precision@k, averaged over seeds.

Usage:
    # Run on an existing indexed DB
    python eval_retrieval.py --db graphrag_code.sqlite

    # Or let it self-index a source directory into a temp DB (defaults to the
    # package's own src/, so it runs out-of-the-box with zero setup):
    python eval_retrieval.py --codebase-dir src

    python eval_retrieval.py --task both --k 3,5,10 --num-seeds 15
"""

import os
import sys
import json
import argparse
import logging
import tempfile
from datetime import datetime
from pathlib import Path

# Make `graphrag_code` importable from the repo root regardless of install state.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from graphrag_code.graph_engine import (
    GraphRAGCodeEngine,
    IMPACT_BACKWARD_WEIGHT,
    CONTEXT_BACKWARD_WEIGHT,
)

logging.getLogger().setLevel(logging.WARNING)  # silence engine INFO logs


# =============================================================================
# GROUND TRUTH - transitive closure over the dependency graph (ranking-agnostic)
# =============================================================================

def _transitive(engine, seed_idx: int, upstream: bool) -> set:
    """All nodes reachable from `seed_idx` following edges in one direction.

    upstream=True  -> transitive predecessors (callers / blast radius).
    upstream=False -> transitive successors  (callees / dependencies).

    The seed itself is excluded. This is independent of any ranking method, so
    it is a fair target for every arm.
    """
    seen = set()
    stack = [seed_idx]
    while stack:
        node = stack.pop()
        neighbors = (
            engine.graph.predecessor_indices(node) if upstream
            else engine.graph.successor_indices(node)
        )
        for nb in neighbors:
            if nb != seed_idx and nb not in seen:
                seen.add(nb)
                stack.append(nb)
    return seen


def ground_truth(engine, seed_idx: int, task: str) -> set:
    """Return the set of relevant FQN names for a seed under the given task."""
    upstream = (task == "blast_radius")
    idxs = _transitive(engine, seed_idx, upstream=upstream)
    return {engine.rx_idx_to_symbol_info[i]["name"] for i in idxs}


# =============================================================================
# RETRIEVAL ARMS - each returns a ranked list of FQN names (best first)
# =============================================================================

def brute_force_arm(engine, seed_idx: int, task: str, top_k: int) -> list:
    """Baseline: direct (1-hop) neighbours only, ranked by total node degree.

    This is the naive "grab everything directly connected" strategy. It has no
    notion of multi-hop relevance, so on graphs with depth > 1 its recall is
    capped by how much of the closure happens to sit one hop away.
    """
    upstream = (task == "blast_radius")
    neighbors = list(
        engine.graph.predecessor_indices(seed_idx) if upstream
        else engine.graph.successor_indices(seed_idx)
    )
    # Naive importance proxy: busier nodes first (in + out degree).
    neighbors.sort(
        key=lambda n: engine.graph.in_degree(n) + engine.graph.out_degree(n),
        reverse=True,
    )
    return [engine.rx_idx_to_symbol_info[n]["name"] for n in neighbors[:top_k]]


def uni_directional_arm(engine, seed_name: str, top_k: int) -> list:
    """Ablation arm: forward-only PPR (backward_weight = 0.0).

    Calls the real engine so the math matches production. With no backward pass,
    pure upstream callers score ~0 and get filtered - by design, to expose the
    limitation that motivates the bidirectional merge.
    """
    results = engine.get_context_ppr(seed_name, top_k=top_k, backward_weight=0.0) or []
    return [r["name"] for r in results]


def bi_directional_arm(engine, seed_name: str, top_k: int, backward_weight: float) -> list:
    """The system: Bidirectional PPR via the real engine entry point.

    `backward_weight` selects the query mode (IMPACT for blast radius,
    CONTEXT for dependencies), exactly as the shipped MCP tools do.
    """
    results = engine.get_context_ppr(
        seed_name, top_k=top_k, backward_weight=backward_weight
    ) or []
    return [r["name"] for r in results]


# =============================================================================
# METRICS
# =============================================================================

def recall_at_k(retrieved: list, relevant: set, k: int) -> float:
    # Set intersection on the top-k prefix: a duplicate name must not be counted
    # twice (standard IR recall, also guards against ambiguous-FQN collisions).
    if not relevant:
        return 0.0
    hits = len(set(retrieved[:k]) & relevant)
    return hits / len(relevant)


def precision_at_k(retrieved: list, relevant: set, k: int) -> float:
    if k <= 0:
        return 0.0
    hits = len(set(retrieved[:k]) & relevant)
    return hits / k


# =============================================================================
# SEED SELECTION
# =============================================================================

def auto_select_seeds(engine, task: str, num_seeds: int) -> list:
    """Pick seeds with a non-trivial ground truth so recall is meaningful.

    blast_radius -> symbols with the most callers (high in-degree).
    dependencies -> symbols that call the most things (high out-degree).
    Modules are skipped (they are containers, not interesting edit targets).
    """
    upstream = (task == "blast_radius")
    scored = []
    for idx in engine.graph.node_indices():
        info = engine.rx_idx_to_symbol_info[idx]
        if info["kind"] == "module":
            continue
        deg = engine.graph.in_degree(idx) if upstream else engine.graph.out_degree(idx)
        if deg >= 1:
            scored.append((deg, idx))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [idx for _, idx in scored[:num_seeds]]


# =============================================================================
# EVALUATION DRIVER
# =============================================================================

ARMS = ["brute_force", "uni_directional", "bi_directional"]


def evaluate_task(engine, task: str, seeds: list, k_values: list) -> dict:
    """Run all arms over all seeds for one task; return aggregated metrics."""
    backward_weight = IMPACT_BACKWARD_WEIGHT if task == "blast_radius" else CONTEXT_BACKWARD_WEIGHT
    max_k = max(k_values)

    recall = {a: {k: [] for k in k_values} for a in ARMS}
    precision = {a: {k: [] for k in k_values} for a in ARMS}
    evaluated_seeds = []

    for seed_idx in seeds:
        seed_name = engine.rx_idx_to_symbol_info[seed_idx]["name"]
        relevant = ground_truth(engine, seed_idx, task)
        if not relevant:
            continue  # nothing to retrieve -> not a useful eval point
        evaluated_seeds.append({"seed": seed_name, "relevant_count": len(relevant)})

        ranked = {
            "brute_force": brute_force_arm(engine, seed_idx, task, max_k),
            "uni_directional": uni_directional_arm(engine, seed_name, max_k),
            "bi_directional": bi_directional_arm(engine, seed_name, max_k, backward_weight),
        }

        for arm in ARMS:
            for k in k_values:
                recall[arm][k].append(recall_at_k(ranked[arm], relevant, k))
                precision[arm][k].append(precision_at_k(ranked[arm], relevant, k))

    def mean(xs):
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    summary = {arm: {} for arm in ARMS}
    for arm in ARMS:
        for k in k_values:
            summary[arm][f"recall@{k}"] = mean(recall[arm][k])
            summary[arm][f"precision@{k}"] = mean(precision[arm][k])

    return {
        "task": task,
        "backward_weight": backward_weight,
        "num_seeds": len(evaluated_seeds),
        "k_values": k_values,
        "seeds": evaluated_seeds,
        "summary": summary,
    }


def evaluate_cases(engine, cases: list, k_values: list) -> dict:
    """Evaluate explicit held-out (seed, task) cases authored by hand.

    Guards against the (mild) circularity of auto-selecting seeds by degree:
    a human picks the symbol and the expected query mode, and we report per-case
    recall for every arm. `seed` may be a short name or a fully-qualified name;
    it is resolved through the engine's normal lookup.
    """
    max_k = max(k_values)
    rows = []
    for case in cases:
        seed_name = case["seed"]
        task = case.get("task", "blast_radius")
        idx = engine.get_node_index(seed_name)
        if idx is None:
            rows.append({"seed": seed_name, "task": task, "error": "symbol not found"})
            continue
        resolved = engine.rx_idx_to_symbol_info[idx]["name"]
        relevant = ground_truth(engine, idx, task)
        bw = IMPACT_BACKWARD_WEIGHT if task == "blast_radius" else CONTEXT_BACKWARD_WEIGHT
        ranked = {
            "brute_force": brute_force_arm(engine, idx, task, max_k),
            "uni_directional": uni_directional_arm(engine, resolved, max_k),
            "bi_directional": bi_directional_arm(engine, resolved, max_k, bw),
        }
        metrics = {
            arm: {f"recall@{k}": round(recall_at_k(ranked[arm], relevant, k), 4) for k in k_values}
            for arm in ARMS
        }
        rows.append({
            "seed": seed_name,
            "resolved": resolved,
            "task": task,
            "note": case.get("note", ""),
            "relevant_count": len(relevant),
            "metrics": metrics,
        })
    return {"mode": "held_out_cases", "k_values": k_values, "cases": rows}


def print_cases_report(report: dict):
    print("\n=== RQ1 | Held-out cases ===")
    for row in report["cases"]:
        if "error" in row:
            print(f"  [SKIP] {row['seed']} ({row['task']}): {row['error']}")
            continue
        print(f"\n  Seed: {row['resolved']}  [task={row['task']}, "
              f"relevant={row['relevant_count']}]"
              + (f"  // {row['note']}" if row['note'] else ""))
        for arm in ARMS:
            cells = "  ".join(f"R@{k}={row['metrics'][arm][f'recall@{k}']:.3f}"
                              for k in report["k_values"])
            print(f"    {arm:<18} {cells}")


# =============================================================================
# REPORTING
# =============================================================================

def print_task_report(report: dict):
    task = report["task"]
    print(f"\n=== RQ1 | Task: {task} (backward_weight={report['backward_weight']}, "
          f"{report['num_seeds']} seeds) ===")
    k_values = report["k_values"]
    header = f"{'Arm':<18}" + "".join(f"R@{k:<6}P@{k:<6}" for k in k_values)
    print(header)
    print("-" * len(header))
    for arm in ARMS:
        row = f"{arm:<18}"
        for k in k_values:
            r = report["summary"][arm][f"recall@{k}"]
            p = report["summary"][arm][f"precision@{k}"]
            row += f"{r:<8.3f}{p:<8.3f}"
        print(row)


def build_markdown(reports: list, meta: dict) -> str:
    lines = [
        "# RQ1 - Structural Retrieval Quality",
        f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
        f"DB: `{meta['db']}` | {meta['nodes']} nodes / {meta['edges']} edges",
        "",
        "Deterministic, LLM-free evaluation. Ground truth = transitive closure over "
        "the dependency graph. Arms compete under a fixed retrieval budget `k`.",
        "",
    ]
    for report in reports:
        lines += [
            f"## Task: `{report['task']}` "
            f"(backward_weight={report['backward_weight']}, {report['num_seeds']} seeds)",
            "",
        ]
        k_values = report["k_values"]
        head = "| Arm | " + " | ".join(f"Recall@{k} | Precision@{k}" for k in k_values) + " |"
        sep = "|-----|" + "|".join(["------|------"] * len(k_values)) + "|"
        lines += [head, sep]
        for arm in ARMS:
            cells = []
            for k in k_values:
                cells.append(f"{report['summary'][arm][f'recall@{k}']:.3f}")
                cells.append(f"{report['summary'][arm][f'precision@{k}']:.3f}")
            lines.append(f"| `{arm}` | " + " | ".join(cells) + " |")
        lines.append("")
    lines += [
        "> Reading the result: on `blast_radius`, `uni_directional` (forward-only) "
        "collapses because upstream callers carry ~zero forward score - this is the "
        "ablation that justifies the bidirectional merge. `brute_force` is capped by "
        "1-hop reach. `bi_directional` is the shipped engine.",
    ]
    return "\n".join(lines)


def save_reports(reports: list, meta: dict, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "rq1_results.json").write_text(
        json.dumps({"meta": meta, "reports": reports}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "rq1_report.md").write_text(build_markdown(reports, meta), encoding="utf-8")
    print(f"\n[OK] Saved: {out_dir / 'rq1_results.json'}")
    print(f"[OK] Saved: {out_dir / 'rq1_report.md'}")


# =============================================================================
# DB BOOTSTRAP (offline, no API key)
# =============================================================================

def load_cases(path: str) -> list:
    """Load held-out cases from a JSON or YAML file.

    Accepts either a bare list of cases or an object with a top-level `cases`
    key. YAML is supported only if PyYAML is installed (JSON needs no deps).
    """
    text = Path(path).read_text(encoding="utf-8")
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml  # optional
        except ImportError:
            raise SystemExit("[!] PyYAML not installed. Use a .json cases file or `pip install pyyaml`.")
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    cases = data.get("cases", data) if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise SystemExit("[!] Cases file must be a list (or an object with a 'cases' list).")
    return cases


def list_seeds(engine, n: int):
    """Print the top-degree symbols (with exact FQN) per task.

    Use this to author `--seeds` / `--cases` files without guessing FQNs:
    the printed names are exactly what the engine resolves against.
    """
    for task in ("blast_radius", "dependencies"):
        print(f"\n# Top {n} seeds for '{task}' (FQN | degree):")
        for idx in auto_select_seeds(engine, task, n):
            info = engine.rx_idx_to_symbol_info[idx]
            deg = engine.graph.in_degree(idx) if task == "blast_radius" else engine.graph.out_degree(idx)
            print(f"  {info['name']}  | {deg}")


def build_db_from_dir(codebase_dir: str) -> str:
    """Index a source directory into a temp SQLite DB and return its path."""
    from graphrag_code.indexer import init_db, scan_directory
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    print(f"[*] Self-indexing '{codebase_dir}' -> {tmp.name}")
    conn = init_db(tmp.name)
    scan_directory(codebase_dir, conn)
    conn.close()
    return tmp.name


# =============================================================================
# CLI
# =============================================================================

def parse_args():
    p = argparse.ArgumentParser(description="RQ1 structural retrieval eval (offline, no LLM)")
    p.add_argument("--db", default=None, help="Path to an existing indexed SQLite DB.")
    p.add_argument("--codebase-dir", default=None,
                   help="Source dir to self-index if --db is not given (default: package src/).")
    p.add_argument("--task", choices=["blast_radius", "dependencies", "both"], default="both")
    p.add_argument("--k", default="3,5,10", help="Comma-separated k values (default: 3,5,10).")
    p.add_argument("--num-seeds", type=int, default=15, help="Max seeds to auto-select per task.")
    p.add_argument("--seeds", default=None, help="Comma-separated seed names (overrides auto-select).")
    p.add_argument("--cases", default=None,
                   help="Path to a JSON/YAML file of held-out {seed, task} cases.")
    p.add_argument("--list-seeds", type=int, default=0, metavar="N",
                   help="Print top-N seed FQNs per task and exit (helps author --cases files).")
    p.add_argument("--out", default="benchmark_results", help="Output directory.")
    return p.parse_args()


def main():
    args = parse_args()
    k_values = sorted({int(x) for x in args.k.split(",") if x.strip()})

    db_path = args.db
    if not db_path:
        codebase_dir = args.codebase_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "src"
        )
        if not os.path.isdir(codebase_dir):
            print(f"[!] No --db given and codebase dir '{codebase_dir}' not found.")
            sys.exit(1)
        db_path = build_db_from_dir(codebase_dir)

    if not os.path.exists(db_path):
        print(f"[!] DB '{db_path}' not found.")
        sys.exit(1)

    engine = GraphRAGCodeEngine(db_path)
    engine.load_graph()
    meta = {"db": db_path, "nodes": engine.graph.num_nodes(), "edges": engine.graph.num_edges()}

    if args.list_seeds:
        list_seeds(engine, args.list_seeds)
        return

    # Held-out cases path: explicit (seed, task) pairs authored by hand.
    if args.cases:
        cases = load_cases(args.cases)
        report = evaluate_cases(engine, cases, k_values)
        print_cases_report(report)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(args.out) / f"rq1_cases_{timestamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "rq1_cases.json").write_text(
            json.dumps({"meta": meta, "report": report}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\n[OK] Saved: {out_dir / 'rq1_cases.json'}")
        return

    tasks = ["blast_radius", "dependencies"] if args.task == "both" else [args.task]

    reports = []
    for task in tasks:
        if args.seeds:
            seeds = []
            for name in args.seeds.split(","):
                idx = engine.get_node_index(name.strip())
                if idx is not None:
                    seeds.append(idx)
        else:
            seeds = auto_select_seeds(engine, task, args.num_seeds)

        if not seeds:
            print(f"[!] No usable seeds for task '{task}', skipping.")
            continue

        report = evaluate_task(engine, task, seeds, k_values)
        reports.append(report)
        print_task_report(report)

    if reports:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_reports(reports, meta, Path(args.out) / f"rq1_{timestamp}")


if __name__ == "__main__":
    main()
