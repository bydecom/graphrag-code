# 📊 GraphRAG-Code Benchmark Results
> Generated: 2026-05-31 02:47:35

## Summary

| Test | Category | Token Savings | Latency Savings | Accuracy Δ |
|------|----------|--------------|----------------|------------|
| TC01 | architecture | 89.3% | -1.0% | +1.00 |
| TC02 | impact_analysis | 97.3% | 54.6% | -0.14 |
| TC03 | architecture | 88.5% | -24.7% | +0.00 |

**Overall: 91.7% token savings · 9.6% latency reduction · Accuracy delta +0.28**

## Detailed Results

### TC01: Which function is responsible for error checking (check validation) in this codebase? Who calls it and what is the execution flow?

| Metric | 🔴 Baseline (Brute-force) | 🟢 GraphRAG-Code PPR | Δ |
|--------|--------------------------|-----------------|---|
| median_tokens | 56970 | 6098 | N/A |
| median_latency | 3.89 | 3.93 | +1.0% |
| median_tool_calls | 0 | 2 | N/A |
| median_accuracy | 0.0 | 1.0 | N/A |

### TC02: If I change the logic in the ship type retrieval function (_get_ship_type), which modules will be affected (blast radius)?

| Metric | 🔴 Baseline (Brute-force) | 🟢 GraphRAG-Code PPR | Δ |
|--------|--------------------------|-----------------|---|
| median_tokens | 50055 | 1334 | N/A |
| median_latency | 6.69 | 3.04 | -54.6% |
| median_tool_calls | 0 | 1 | N/A |
| median_accuracy | 0.57 | 0.43 | -0.14 |

### TC03: What components make up the BayMenu class? How does the render_grid method work?

| Metric | 🔴 Baseline (Brute-force) | 🟢 GraphRAG-Code PPR | Δ |
|--------|--------------------------|-----------------|---|
| median_tokens | 57208 | 6567 | N/A |
| median_latency | 4.53 | 5.65 | +24.7% |
| median_tool_calls | 0 | 1 | N/A |
| median_accuracy | 1.0 | 1.0 | +0.0% |
