"""
benchmark_suite.py — GraphRAG-Code vs Brute-Force Benchmark
=========================================================
Empirical measurement: Token cost, latency, tool calls, accuracy
Usage: python benchmark_suite.py --db graphrag_code.sqlite --runs 3

Requirements:
    pip install litellm mcp tiktoken rich

Output structure:
    benchmark_results/
        run_YYYYMMDD_HHMMSS/
            results.json       ← raw data
            report.md          ← markdown table for README
            summary.txt        ← terminal summary
"""

import asyncio
import json
import os
import sys
import time
import argparse
import statistics
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

import litellm
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ── Optional: use tiktoken for accurate token counting ──────────────────────
try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    def count_tokens(text: str) -> int:
        return len(_enc.encode(text))
except ImportError:
    def count_tokens(text: str) -> int:
        # Fallback: approx 1 token ~ 4 chars
        return len(text) // 4

# ── Optional: rich for beautiful terminal output ─────────────────────────────────────────
try:
    from rich.console import Console
    from rich.table import Table
    from rich.progress import track
    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    class _FakeConsole:
        def print(self, *a, **kw): print(*a)
        def rule(self, *a, **kw): print("─" * 60)
    console = _FakeConsole()


# ══════════════════════════════════════════════════════════════════════════════
# PART 1: DEFINE TEST CASES
# Modify this section to fit your codebase
# ══════════════════════════════════════════════════════════════════════════════

TEST_CASES = [
    {
        "id": "TC01",
        "question": "Which function is responsible for validation error checking in this codebase? Who calls it and how does it flow?",
        "seed_node": "check_validation_errors",
        "category": "architecture",
        "expected_keywords": ["minibaycanvas", "update_status_border"], 
    },
    {
        "id": "TC02",
        "question": "If I change the logic in the ship type retrieval function (_get_ship_type), which modules will be affected (blast radius)?",
        "seed_node": "_get_ship_type",
        "category": "impact_analysis",
        "expected_keywords": ["ship", "bay", "affect", "call", "import", "depend", "module"],
    },
    {
        "id": "TC03",
        "question": "What components make up the BayMenu class? How does the render_grid method work?",
        "seed_node": "BayMenu",
        "category": "architecture",
        "expected_keywords": ["render_grid", "canvas", "grid"],
    }
]

# ── You can add custom test cases here ────────────────────────────────────────
CUSTOM_TEST_CASES = []  


# ══════════════════════════════════════════════════════════════════════════════
# PART 2: DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RunMetrics:
    """Metrics for a single run."""
    tokens_input: int = 0
    tokens_output: int = 0
    tool_calls: int = 0
    latency_seconds: float = 0.0
    answer_text: str = ""
    accuracy_score: float = 0.0     # 0.0 → 1.0 based on keyword matching
    error: Optional[str] = None
    messages_history: list = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.tokens_input + self.tokens_output

    @property
    def cost_usd_estimate(self) -> float:
        # Approximate Gemini Flash pricing (adjust based on your model)
        input_cost = self.tokens_input * 0.075 / 1_000_000
        output_cost = self.tokens_output * 0.30 / 1_000_000
        return round(input_cost + output_cost, 6)


@dataclass
class TestResult:
    """Aggregated results for a test case (multiple runs)."""
    test_id: str
    question: str
    category: str

    graphrag_code_runs: list[RunMetrics] = field(default_factory=list)
    baseline_runs:  list[RunMetrics] = field(default_factory=list)

    def _median(self, values: list[float]) -> float:
        return statistics.median(values) if values else 0.0

    def _valid_runs(self, runs: list[RunMetrics]) -> list[RunMetrics]:
        return [r for r in runs if r.error is None]

    def summary(self, arm: str) -> dict:
        runs = self._valid_runs(
            self.graphrag_code_runs if arm == "graphrag_code" else self.baseline_runs
        )
        if not runs:
            return {"error": "All runs failed"}
        return {
            "median_tokens":    self._median([r.total_tokens for r in runs]),
            "median_latency":   round(self._median([r.latency_seconds for r in runs]), 2),
            "median_tool_calls": self._median([r.tool_calls for r in runs]),
            "median_accuracy":  round(self._median([r.accuracy_score for r in runs]), 2),
            "median_cost_usd":  round(self._median([r.cost_usd_estimate for r in runs]), 6),
            "valid_runs":       len(runs),
        }

    def savings(self) -> dict:
        cg = self.summary("graphrag_code")
        bl = self.summary("baseline")
        if "error" in cg or "error" in bl:
            return {}

        def pct(after, before):
            return round((1 - after / before) * 100, 1) if before > 0 else 0.0

        return {
            "token_savings_pct":    pct(cg["median_tokens"],    bl["median_tokens"]),
            "latency_savings_pct":  pct(cg["median_latency"],   bl["median_latency"]),
            "tool_call_savings_pct": pct(cg["median_tool_calls"], bl["median_tool_calls"]),
            "accuracy_delta":       round(cg["median_accuracy"] - bl["median_accuracy"], 2),
        }


# ══════════════════════════════════════════════════════════════════════════════
# PART 3: AGENT RUNNERS
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT_CODEGRAPH = """You are an AI Software Architect. Please analyze the codebase provided via GraphRAG-Code tools.

MANDATORY Workflow:
1. Call `list_symbols` to get an overview of the codebase.
2. Call `get_pruned_context` with an appropriate seed_node to get exact context.
3. If you need to know who calls a function, use `get_callers`.
4. Answer concisely and accurately based on REAL CODE from the tools — do not guess.

Do not attempt to read files manually. Only use the provided tools."""

SYSTEM_PROMPT_BASELINE = """You are an AI Software Architect. Analyze the codebase provided below.

Please answer the question based on the code provided in the context. Answer concisely and accurately."""


def _calc_accuracy(answer: str, expected_keywords: list[str]) -> float:
    """Calculate simple accuracy based on keyword matching (0.0–1.0)."""
    if not expected_keywords:
        return 1.0
    answer_lower = answer.lower()
    hits = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)
    return round(hits / len(expected_keywords), 2)


async def run_graphrag_code_agent(
    question: str,
    seed_node: Optional[str],
    expected_keywords: list[str],
    db_path: str,
    model: str,
    api_key: str,
) -> RunMetrics:
    """Run agent with GraphRAG-Code MCP tools."""
    metrics = RunMetrics()
    start = time.perf_counter()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["GRAPHRAG_CODE_DB"] = db_path

    # Call mcp server as a Python module (after refactoring into src directory)
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "graphrag_code.mcp_server"],
        env=env
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                mcp_tools = await session.list_tools()
                llm_tools = [
                    {
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.inputSchema,
                        }
                    }
                    for t in mcp_tools.tools
                ]

                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT_CODEGRAPH},
                    {"role": "user",   "content": question},
                ]

                # If there's a suggested seed_node, add it to the context
                if seed_node:
                    messages[1]["content"] += f"\n\n[Hint: start from symbol '{seed_node}']"

                # Agent loop
                for _ in range(10):   # max 10 tool calling iterations
                    response = await litellm.acompletion(
                        model=model,
                        messages=messages,
                        tools=llm_tools,
                        api_key=api_key,
                    )

                    msg = response.choices[0].message
                    metrics.tokens_input  += response.usage.prompt_tokens
                    metrics.tokens_output += response.usage.completion_tokens

                    msg_dict = msg.model_dump(exclude_none=True)
                    messages.append(msg_dict)

                    if msg.tool_calls:
                        for tc in msg.tool_calls:
                            metrics.tool_calls += 1
                            args = json.loads(tc.function.arguments)
                            result = await session.call_tool(tc.function.name, arguments=args)
                            result_text = "\n".join(
                                c.text for c in result.content if c.type == "text"
                            )
                            messages.append({
                                "role":        "tool",
                                "tool_call_id": tc.id,
                                "name":         tc.function.name,
                                "content":      result_text,
                            })
                    else:
                        # Agent finished
                        metrics.answer_text    = msg.content or ""
                        metrics.accuracy_score = _calc_accuracy(
                            metrics.answer_text, expected_keywords
                        )
                        break

    except Exception as e:
        metrics.error = str(e)

    metrics.latency_seconds = round(time.perf_counter() - start, 2)
    return metrics


async def run_baseline_agent(
    question: str,
    expected_keywords: list[str],
    codebase_dump: str,
    model: str,
    api_key: str,
) -> RunMetrics:
    """Run brute-force agent: inject entire codebase into context."""
    metrics = RunMetrics()
    start = time.perf_counter()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_BASELINE},
        {
            "role": "user",
            "content": f"CODEBASE:\n\n{codebase_dump}\n\nQUESTION: {question}"
        },
    ]

    try:
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            api_key=api_key,
        )
        metrics.tokens_input  = response.usage.prompt_tokens
        metrics.tokens_output = response.usage.completion_tokens
        metrics.tool_calls    = 0   # Brute-force does not use tools
        metrics.answer_text   = response.choices[0].message.content or ""
        metrics.accuracy_score = _calc_accuracy(metrics.answer_text, expected_keywords)

    except Exception as e:
        metrics.error = str(e)

    metrics.latency_seconds = round(time.perf_counter() - start, 2)
    return metrics


# ══════════════════════════════════════════════════════════════════════════════
# PART 4: CODEBASE DUMP (for baseline arm)
# ══════════════════════════════════════════════════════════════════════════════

def build_codebase_dump(codebase_dir: str, max_files: int = 50) -> str:
    """
    Read all .py files in the directory and concatenate them into a large string.
    This is how brute-force agents operate (full codebase in context).
    """
    parts = []
    count = 0
    for root, _, files in os.walk(codebase_dir):
        for fname in sorted(files):
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            try:
                content = Path(fpath).read_text(encoding="utf-8", errors="replace")
                parts.append(f"# FILE: {fpath}\n{content}\n")
                count += 1
                if count >= max_files:
                    parts.append(f"\n# ... (truncated, {max_files} files shown)")
                    return "\n".join(parts)
            except Exception:
                pass
    return "\n".join(parts) if parts else "# (no Python files found)"


# ══════════════════════════════════════════════════════════════════════════════
# PART 5: REPORTING
# ══════════════════════════════════════════════════════════════════════════════

def save_results(results: list[TestResult], output_dir: Path):
    """Save results to JSON and Markdown."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Raw JSON ─────────────────────────────────────────────────────────────
    raw = []
    for r in results:
        raw.append({
            "test_id":  r.test_id,
            "question": r.question,
            "category": r.category,
            "graphrag_code": r.summary("graphrag_code"),
            "baseline":  r.summary("baseline"),
            "savings":   r.savings(),
        })
    json_path = output_dir / "results.json"
    json_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False))

    # ── Markdown report ───────────────────────────────────────────────────────
    lines = [
        "# 📊 GraphRAG-Code Benchmark Results",
        f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Summary",
        "",
        "| Test | Category | Token Savings | Latency Savings | Accuracy Δ |",
        "|------|----------|--------------|----------------|------------|",
    ]
    for r in results:
        s = r.savings()
        if s:
            lines.append(
                f"| {r.test_id} | {r.category} "
                f"| {s['token_savings_pct']}% "
                f"| {s['latency_savings_pct']}% "
                f"| {s['accuracy_delta']:+.2f} |"
            )
        else:
            lines.append(f"| {r.test_id} | {r.category} | N/A | N/A | N/A |")

    # Aggregate
    valid = [r for r in results if r.savings()]
    if valid:
        avg_token = round(statistics.mean(r.savings()["token_savings_pct"] for r in valid), 1)
        avg_lat   = round(statistics.mean(r.savings()["latency_savings_pct"] for r in valid), 1)
        avg_acc   = round(statistics.mean(r.savings()["accuracy_delta"] for r in valid), 2)
        lines += [
            "",
            f"**Overall: {avg_token}% token savings · {avg_lat}% latency reduction · Accuracy delta {avg_acc:+.2f}**",
        ]

    lines += ["", "## Detailed Results", ""]
    for r in results:
        cg = r.summary("graphrag_code")
        bl = r.summary("baseline")
        lines += [
            f"### {r.test_id}: {r.question[:80]}...",
            "",
            "| Metric | 🔴 Baseline (Brute-force) | 🟢 GraphRAG-Code PPR | Δ |",
            "|--------|--------------------------|-----------------|---|",
        ]
        for metric in ["median_tokens", "median_latency", "median_tool_calls", "median_accuracy"]:
            cg_val = cg.get(metric, "N/A")
            bl_val = bl.get(metric, "N/A")
            if isinstance(cg_val, float) and isinstance(bl_val, float) and bl_val > 0:
                delta = f"{((cg_val - bl_val) / bl_val * 100):+.1f}%"
            else:
                delta = "N/A"
            lines.append(f"| {metric} | {bl_val} | {cg_val} | {delta} |")
        lines.append("")

    md_path = output_dir / "report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    console.print(f"\n✅ Results saved to: [bold]{output_dir}[/bold]")
    console.print(f"   📄 JSON:     {json_path}")
    console.print(f"   📝 Markdown: {md_path}")

    return raw


def print_summary_table(results: list[TestResult]):
    """Print summary table to terminal."""
    if not HAS_RICH:
        print("\n=== BENCHMARK SUMMARY ===")
        for r in results:
            s = r.savings()
            print(f"{r.test_id}: token_savings={s.get('token_savings_pct', 'N/A')}%")
        return

    table = Table(title="📊 Benchmark Summary", show_lines=True)
    table.add_column("Test",      style="cyan",  no_wrap=True)
    table.add_column("Category",  style="magenta")
    table.add_column("Tokens BL", justify="right")
    table.add_column("Tokens CG", justify="right")
    table.add_column("Token Δ",   justify="right", style="green")
    table.add_column("Latency Δ", justify="right", style="yellow")
    table.add_column("Acc Δ",     justify="right")

    for r in results:
        cg = r.summary("graphrag_code")
        bl = r.summary("baseline")
        s  = r.savings()
        if "error" in cg or "error" in bl or not s:
            table.add_row(r.test_id, r.category, "ERR", "ERR", "-", "-", "-")
        else:
            acc_color = "green" if s["accuracy_delta"] >= 0 else "red"
            table.add_row(
                r.test_id,
                r.category,
                f"{bl['median_tokens']:,.0f}",
                f"{cg['median_tokens']:,.0f}",
                f"[green]-{s['token_savings_pct']}%[/green]",
                f"[yellow]-{s['latency_savings_pct']}%[/yellow]",
                f"[{acc_color}]{s['accuracy_delta']:+.2f}[/{acc_color}]",
            )

    console.print(table)


# ══════════════════════════════════════════════════════════════════════════════
# PART 6: MAIN ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

async def run_benchmark(args):
    api_key = args.api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        console.print("[red]❌ Need to set GEMINI_API_KEY or OPENAI_API_KEY[/red]")
        sys.exit(1)

    all_cases = TEST_CASES + CUSTOM_TEST_CASES
    if args.test_ids:
        ids = set(args.test_ids.split(","))
        all_cases = [t for t in all_cases if t["id"] in ids]

    console.rule(f"[bold cyan]GraphRAG-Code Benchmark Suite[/bold cyan]")
    console.print(f"  Model:    {args.model}")
    console.print(f"  DB:       {args.db}")
    console.print(f"  Runs/arm: {args.runs}")
    console.print(f"  Tests:    {len(all_cases)}")
    console.rule()

    # Build codebase dump for baseline arm
    codebase_dump = ""
    if args.codebase_dir:
        console.print(f"[dim]Building codebase dump from: {args.codebase_dir}[/dim]")
        codebase_dump = build_codebase_dump(args.codebase_dir, max_files=args.max_files)
        tokens_in_dump = count_tokens(codebase_dump)
        console.print(f"[dim]Dump size: ~{tokens_in_dump:,} tokens ({len(codebase_dump):,} chars)[/dim]")
    else:
        console.print("[yellow]⚠️  --codebase-dir not provided. Baseline arm will use empty dump.[/yellow]")

    results: list[TestResult] = []

    for tc in all_cases:
        console.rule(f"[bold]{tc['id']}: {tc['question'][:60]}...[/bold]")
        result = TestResult(
            test_id=tc["id"],
            question=tc["question"],
            category=tc["category"],
        )

        # ── GraphRAG-Code arm ────────────────────────────────────────────────────
        console.print(f"  [cyan]→ Running GraphRAG-Code arm ({args.runs} runs)...[/cyan]")
        for run_idx in range(args.runs):
            console.print(f"    Run {run_idx+1}/{args.runs}", end=" ")
            metrics = await run_graphrag_code_agent(
                question=tc["question"],
                seed_node=tc.get("seed_node"),
                expected_keywords=tc.get("expected_keywords", []),
                db_path=args.db,
                model=args.model,
                api_key=api_key,
            )
            result.graphrag_code_runs.append(metrics)
            if metrics.error:
                console.print(f"[red]ERROR: {metrics.error}[/red]")
            else:
                console.print(
                    f"[green]✓[/green] tokens={metrics.total_tokens:,} "
                    f"tools={metrics.tool_calls} "
                    f"lat={metrics.latency_seconds}s "
                    f"acc={metrics.accuracy_score:.2f}"
                )

            # Cooldown between runs to avoid rate limiting
            if run_idx < args.runs - 1:
                await asyncio.sleep(args.cooldown)

        # ── Baseline arm ─────────────────────────────────────────────────────
        if not args.skip_baseline:
            console.print(f"  [yellow]→ Running Baseline arm ({args.runs} runs)...[/yellow]")
            for run_idx in range(args.runs):
                console.print(f"    Run {run_idx+1}/{args.runs}", end=" ")
                metrics = await run_baseline_agent(
                    question=tc["question"],
                    expected_keywords=tc.get("expected_keywords", []),
                    codebase_dump=codebase_dump,
                    model=args.model,
                    api_key=api_key,
                )
                result.baseline_runs.append(metrics)
                if metrics.error:
                    console.print(f"[red]ERROR: {metrics.error}[/red]")
                else:
                    console.print(
                        f"[yellow]✓[/yellow] tokens={metrics.total_tokens:,} "
                        f"tools={metrics.tool_calls} "
                        f"lat={metrics.latency_seconds}s "
                        f"acc={metrics.accuracy_score:.2f}"
                    )

                if run_idx < args.runs - 1:
                    await asyncio.sleep(args.cooldown)

        results.append(result)

    # ── Print summary ────────────────────────────────────────────────────────
    console.rule()
    print_summary_table(results)

    # ── Save results ─────────────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) / f"run_{timestamp}"
    save_results(results, out_dir)

    return results


# ══════════════════════════════════════════════════════════════════════════════
# PART 7: CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(
        description="GraphRAG-Code Benchmark Suite — measure token savings vs brute-force"
    )
    parser.add_argument(
        "--db",
        default="graphrag_code.sqlite",
        help="Path to SQLite database of GraphRAG-Code (default: graphrag_code.sqlite)"
    )
    parser.add_argument(
        "--codebase-dir",
        default=None,
        help="Directory containing source code to build baseline dump (default: None)"
    )
    parser.add_argument(
        "--model",
        default="gemini/gemini-2.5-flash-lite",
        help="LiteLLM model string (default: gemini/gemini-2.5-flash-lite)"
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key (or set env GEMINI_API_KEY / OPENAI_API_KEY)"
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of runs per arm to get median (default: 3)"
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=2.0,
        help="Seconds to rest between runs to avoid rate limits (default: 2.0)"
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=50,
        help="Max files to include in baseline dump (default: 50)"
    )
    parser.add_argument(
        "--output-dir",
        default="benchmark_results",
        help="Directory to save results (default: benchmark_results/)"
    )
    parser.add_argument(
        "--test-ids",
        default=None,
        help="Only run specific test IDs, separated by commas (e.g. TC01,TC03)"
    )
    parser.add_argument(
        "--skip-baseline",
        action="store_true",
        help="Skip baseline arm, only benchmark GraphRAG-Code (useful for debugging)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print config, do not run"
    )
    return parser.parse_args()


def main():
    litellm.suppress_debug_info = True

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    args = parse_args()

    if args.dry_run:
        console.print("[bold yellow]DRY RUN — config:[/bold yellow]")
        console.print(vars(args))
        console.print(f"\nTest cases to run: {len(TEST_CASES + CUSTOM_TEST_CASES)}")
        sys.exit(0)

    asyncio.run(run_benchmark(args))


if __name__ == "__main__":
    main()
