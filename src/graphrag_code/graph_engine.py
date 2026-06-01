import sqlite3
import rustworkx as rx
import os
import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')

# ─────────────────────────────────────────────────────────────────────────────
# Backward-weight presets — single source of truth for the merge magic numbers.
# These tune how strongly the backward (upstream/caller) PPR pass influences the
# final ranking. Tools across the codebase MUST reference these constants instead
# of hardcoding values, so the behaviour stays consistent and reviewable.
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_BACKWARD_WEIGHT = 0.2   # structural/dependency context (non-linear merge)
CONTEXT_BACKWARD_WEIGHT = 0.3   # 360° context view, still leans downstream
IMPACT_BACKWARD_WEIGHT = 0.9    # blast-radius / upstream callers (linear merge)
MERGE_MODE_THRESHOLD = 0.5      # >= switches from non-linear damping to linear merge


class GraphRAGCodeEngine:
    def __init__(self, db_path="graphrag_code.sqlite"):
        self.db_path = db_path
        self.graph = rx.PyDiGraph()
        # Mapping between SQLite ID and Rustworkx Node Index
        self.sqlite_id_to_rx_idx = {}
        self.rx_idx_to_symbol_info = {}
        self.name_to_rx_idx = {}  # O(1) lookup map

    def load_graph(self):
        """
        Loads data from SQLite into the in-memory rustworkx graph.
        
        Raises:
            FileNotFoundError: If the database file does not exist (indexer hasn't run).
            RuntimeError: If there's an SQLite connection or query error.
        """
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"❌ [DB ERROR] '{self.db_path}' not found. Please run the indexer first!")
            
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
        except sqlite3.Error as e:
            raise RuntimeError(f"❌ [DB CONNECTION ERROR] {e}")

        # 1. Load all Symbols (Nodes)
        # JOIN with files table to obtain the file_path
        query_symbols = """
            SELECT s.id, s.name, s.kind, s.start_line, s.end_line, f.file_path 
            FROM symbols s
            JOIN files f ON s.file_id = f.id
        """
        cursor.execute(query_symbols)
        symbols = cursor.fetchall()
        
        for sym_id, name, kind, start, end, file_path in symbols:
            # Store metadata for precise code block extraction
            node_data = {
                "id": sym_id, "name": name, "kind": kind, 
                "start_line": start, "end_line": end, "file_path": file_path
            }
            rx_idx = self.graph.add_node(node_data)
            
            # Save mapping
            self.sqlite_id_to_rx_idx[sym_id] = rx_idx
            self.rx_idx_to_symbol_info[rx_idx] = node_data
            
            # Issue B: Handle duplicate symbol names (like multiple validate() methods)
            if name not in self.name_to_rx_idx:
                self.name_to_rx_idx[name] = rx_idx
            else:
                existing = self.name_to_rx_idx[name]
                if isinstance(existing, list):
                    existing.append(rx_idx)
                else:
                    self.name_to_rx_idx[name] = [existing, rx_idx]

        # 2. Load Edges from central SQL VIEW
        # The `resolved_edges` VIEW already resolves cross-file import/extends logic (DRY)
        query_edges = "SELECT source_id, target_id, edge_type FROM resolved_edges"
        cursor.execute(query_edges)
        edges = cursor.fetchall()

        # Build edge list for rustworkx (source_idx, target_idx, edge_data)
        rx_edges = []
        for source_sqlite_id, target_sqlite_id, edge_type in edges:
            src_idx = self.sqlite_id_to_rx_idx.get(source_sqlite_id)
            tgt_idx = self.sqlite_id_to_rx_idx.get(target_sqlite_id)
            
            if src_idx is not None and tgt_idx is not None:
                # Save edge metadata: type + weight
                rx_edges.append((src_idx, tgt_idx, {"weight": 1.0, "type": edge_type}))

        # Batch add edges using C-backend
        self.graph.add_edges_from(rx_edges)
        
        # Build reversed graph for Bidirectional PPR
        self.reversed_graph = rx.PyDiGraph()
        for idx in sorted(self.graph.node_indices()):
            # Issue 3: Add None instead of duplicating node metadata to save ~50% RAM
            self.reversed_graph.add_node(None) 
        for src, tgt, data in self.graph.weighted_edge_list():
            # Only duplicate the weight needed for PageRank, not the whole dict
            self.reversed_graph.add_edge(tgt, src, {"weight": data.get("weight", 1.0)})
        
        conn.close()
        
        logging.info(f"[-] Successfully loaded Graph: {self.graph.num_nodes()} Nodes, {self.graph.num_edges()} Edges (+ reversed graph).")

    def get_node_index(self, symbol_name: str):
        """Resolve a symbol name to its rustworkx index.

        Exact match is O(1) via the `name_to_rx_idx` dict. If that misses, we fall
        back to an O(N) suffix scan to resolve short names against stored FQNs
        (e.g. 'GraphEngine' -> '<module: engine.py>::GraphEngine').
        """
        # 1. Exact match
        if symbol_name in self.name_to_rx_idx:
            idx = self.name_to_rx_idx[symbol_name]
            if isinstance(idx, list):
                logging.warning(f"[!] Ambiguous symbol '{symbol_name}': found {len(idx)} matches. Using first occurrence.")
                return idx[0]
            return idx
            
        # 2. Suffix match (e.g. searching 'GraphEngine' matches '<module: engine.py>::GraphEngine')
        matches = []
        for name, idx in self.name_to_rx_idx.items():
            if name.endswith(f"::{symbol_name}") or name.endswith(f".{symbol_name}"):
                if isinstance(idx, list):
                    matches.extend(idx)
                else:
                    matches.append(idx)
                    
        if matches:
            if len(matches) > 1:
                logging.warning(f"[!] Ambiguous symbol '{symbol_name}': found {len(matches)} matches (Suffix). Using first occurrence.")
            return matches[0]
            
        return None

    def _extract_source_code(self, file_path, start_line, end_line):
        """Internal helper: Read the file and slice the exact code block (O(1) I/O)"""
        # Resolve absolute paths (relative to the directory containing the SQLite DB)
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        abs_file_path = file_path if os.path.isabs(file_path) else os.path.join(db_dir, file_path)

        if not os.path.exists(abs_file_path):
            return f"<Source file not found on disk: {abs_file_path}>"
        
        try:
            with open(abs_file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.read().splitlines()
                # Tree-sitter is 0-indexed, Python slice goes to end_line + 1
                snippet = "\n".join(lines[start_line:end_line + 1])
                return snippet
        except Exception as e:
            return f"<Error reading file: {str(e)}>"

    def _get_expanded_seeds(self, seed_idx) -> list:
        """
        Interface-Consumer Expansion.
        If the seed is a Child that implements/extends Interface I,
        retrieve the Parent (I) and all Siblings (Child2) that also implement Interface I.
        Resolves dynamic polymorphism dependencies via interface mappings.
        """
        interfaces = set()
        # Find all interfaces that the seed implements/extends
        for succ in self.graph.successor_indices(seed_idx):
            edges = self.graph.get_all_edge_data(seed_idx, succ)
            if any(isinstance(e, dict) and e.get("type") == "extends" for e in edges):
                interfaces.add(succ)
                
        expanded_seeds = {seed_idx}
        # Trace back from interface to all consumers (classes extending/implementing it)
        for iface in interfaces:
            expanded_seeds.add(iface)  # Boost weight for the interface itself
            for pred in self.graph.predecessor_indices(iface):
                edges = self.graph.get_all_edge_data(pred, iface)
                if any(isinstance(e, dict) and e.get("type") == "extends" for e in edges):
                    expanded_seeds.add(pred)
                    
        return list(expanded_seeds)

    def get_context_ppr(self, seed_name: str, top_k: int = 5,
                        backward_weight: float = DEFAULT_BACKWARD_WEIGHT):
        """
        Runs Personalized PageRank in BOTH edge directions and merges the results.

        This is NOT the Lofgren et al. (2016) bidirectional PPR *estimator*. Here we
        run two independent, full PPR passes and combine their score vectors:
          - Forward PPR (on the original graph): downstream dependencies
            (A calls B → retrieve B).
          - Backward PPR (on the reversed graph): upstream consumers/callers
            (C calls A → retrieve C / blast radius).

        The two passes are then merged with `backward_weight`. Because a pure caller
        has ~zero forward score, low weights (< MERGE_MODE_THRESHOLD) effectively
        favour downstream context, while high weights surface upstream callers. In
        practice this means the engine serves two distinct query modes depending on
        the weight, rather than one symmetric "see everything" query.

        Args:
            backward_weight: Scale factor for upstream scores (0.0-1.0).
                             Default is DEFAULT_BACKWARD_WEIGHT (downstream-leaning).
                             Use IMPACT_BACKWARD_WEIGHT for blast-radius queries.
        """
        seed_idx = self.get_node_index(seed_name)
                
        if seed_idx is None:
            logging.warning(f"[!] Symbol '{seed_name}' not found in the Graph.")
            return None

        logging.info(f"\n[🚀] Launching Bidirectional PPR from Seed: '{seed_name}'")

        # Expand seeds if hitting an Interface
        expanded_seeds = self._get_expanded_seeds(seed_idx)
        if len(expanded_seeds) > 1:
            names = [self.rx_idx_to_symbol_info[idx]["name"] for idx in expanded_seeds]
            logging.info(f"  [+] Interface Expansion triggered! Seed group: {names}")

        # Configure Personalization vector: Concentrate teleport energy on Seed Nodes
        personalization = {n: 0.0 for n in self.graph.node_indices()}
        for n in expanded_seeds:
            personalization[n] = 1.0 / len(expanded_seeds)

        # Weight function compatible with both dict metadata and float legacy formats
        weight_fn = lambda x: x["weight"] if isinstance(x, dict) else float(x)

        # Forward PPR: downstream dependencies
        forward_scores = dict(rx.pagerank(
            self.graph, 
            alpha=0.85, 
            weight_fn=weight_fn,
            personalization=personalization
        ))

        # Backward PPR: upstream consumers (runs on reversed graph)
        backward_personalization = {n: 0.0 for n in self.reversed_graph.node_indices()}
        for n in expanded_seeds:
            if n in backward_personalization:
                backward_personalization[n] = 1.0 / len(expanded_seeds)
                
        backward_scores = dict(rx.pagerank(
            self.reversed_graph,
            alpha=0.85,
            weight_fn=weight_fn,
            personalization=backward_personalization
        ))

        # Merge scores: Non-linear merge to prevent domination (Issue 2)
        merged_scores = {}
        for idx in self.graph.node_indices():
            fwd = forward_scores.get(idx, 0.0)
            bwd = backward_scores.get(idx, 0.0)
            
            # Harmonic-like merge: Dampen backward impact if forward is very weak (unless we are looking for blast radius)
            if backward_weight < MERGE_MODE_THRESHOLD:
                # For context understanding: rely on fwd, heavily penalize callers that don't give forward info
                merged_scores[idx] = fwd + (bwd * backward_weight * (fwd + 1e-4))
            else:
                # For blast radius (backward_weight >= 0.5): pure linear is acceptable as we care about callers
                merged_scores[idx] = fwd * (1.0 - backward_weight) + bwd * backward_weight

        # Issue 1: Remove expanded seeds from merged scores so the agent doesn't get what it already knows
        for n in expanded_seeds:
            if n in merged_scores:
                del merged_scores[n]

        # Sort nodes by score descending - Complexity: O(|V| log |V|)
        ranked_nodes = sorted(merged_scores.items(), key=lambda item: item[1], reverse=True)

        # Retrieve top_k results
        pruned_context = []
        for rx_idx, score in ranked_nodes[:top_k]:
            # Filter on the rounded score we actually report: a value that rounds to
            # 0.0000 is noise (e.g. a pure caller under the non-linear damping at low
            # backward_weight) and would only clutter the agent's context.
            rounded_score = round(score, 4)
            if rounded_score > 0:
                symbol_data = self.rx_idx_to_symbol_info[rx_idx]
                
                # Extract precise code snippet
                source_code = self._extract_source_code(
                    symbol_data["file_path"], 
                    symbol_data["start_line"], 
                    symbol_data["end_line"]
                )
                
                pruned_context.append({
                    "name": symbol_data["name"],
                    "kind": symbol_data["kind"],
                    "score": rounded_score,
                    "fwd_score": round(forward_scores.get(rx_idx, 0.0), 4),
                    "bwd_score": round(backward_scores.get(rx_idx, 0.0), 4),
                    "file_path": symbol_data["file_path"],
                    "source_code": source_code
                })

        return pruned_context

if __name__ == "__main__":
    import sys
    db_file = sys.argv[1] if len(sys.argv) > 1 else "graphrag_code.sqlite"
    seed_node = sys.argv[2] if len(sys.argv) > 2 else "process_checkout"
    
    engine = GraphRAGCodeEngine(db_file)
    engine.load_graph()
    
    context = engine.get_context_ppr(seed_name=seed_node, top_k=10)
    
    logging.info(f"\n=== PRUNED CONTEXT FOR '{seed_node}' ===")
    for rank, item in enumerate(context, 1):
        logging.info(f"#{rank} | Score: {item['score']} | {item['kind'].capitalize()}: {item['name']}")
