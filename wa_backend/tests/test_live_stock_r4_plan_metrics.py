"""Negative controls for performance evidence: inclusive buffers and key bounds."""
import pytest
from scripts.gate_r4_live_stock_perf_50k import plan_metrics, bounded_candidates


def test_buffer_totals_do_not_double_count_postgres_parent_nodes():
    child = {"Node Type": "Index Scan", "Shared Hit Blocks": 90,
             "Actual Rows": 50, "Actual Loops": 1, "Index Name": "seek"}
    top = {"Execution Time": 1, "Planning Time": 2, "Plan": {
        "Node Type": "Nested Loop", "Shared Hit Blocks": 100, "Plans": [child]}}
    metrics = plan_metrics(top)
    assert metrics["root_buffers"]["Shared Hit Blocks"] == 100
    assert metrics["legacy_inclusive_hit_sum"] == 190
    assert metrics["indexes"] == ["seek"]


def test_gate_rejects_unbounded_candidates_even_if_final_page_is_small():
    top = {"Plan": {"Plans": [
        {"Subplan Name": "CTE inventory_page_candidates", "Actual Rows": 51},
        {"Subplan Name": "CTE inventory_detail_keys", "Actual Rows": 50},
    ]}}
    bounded_candidates(top, 50)
    top["Plan"]["Plans"][0]["Actual Rows"] = 50000
    with pytest.raises(AssertionError):
        bounded_candidates(top, 50)
