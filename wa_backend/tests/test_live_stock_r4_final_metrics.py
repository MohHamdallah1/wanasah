"""Negative controls for actual R4 metrics; no fixture, runtime or security mocks."""
import pytest

from scripts.live_stock_r4_final_metrics import (
    assert_bounded_plan, assert_constant_counts, assert_selective_point_scans,
    distribution, plan_evidence,
)


def test_percentiles_use_explicit_nearest_rank_and_keep_raw_tail():
    result = distribution(list(range(1, 101)))
    assert result["n"] == 100
    assert (result["p50_ms"], result["p95_ms"], result["p99_ms"], result["max_ms"]) == (50, 95, 99, 100)
    assert distribution([1, 2, 9])["p99_ms"] == 9
    with pytest.raises(AssertionError):
        distribution([])


def test_buffers_are_root_totals_and_scanned_work_preserves_loops():
    top = {"Execution Time": 1, "Planning Time": 2, "Plan": {
        "Node Type": "Nested Loop", "Shared Hit Blocks": 100, "Shared Read Blocks": 25,
        "Plans": [{"Node Type": "Index Scan", "Relation Name": "product_variants",
                   "Index Name": "seek", "Shared Hit Blocks": 90,
                   "Actual Rows": 2, "Rows Removed by Filter": 3, "Actual Loops": 10000}]}}
    result = plan_evidence(top, 50000)
    assert result["root_buffers"]["Shared Hit Blocks"] == 100
    assert result["shared_buffer_hit_fraction"] == .8
    assert result["scans"][0]["emitted_plus_filter_rows_x_loops"] == 50000
    assert result["scans"][0]["catalog_sized_work"]
    assert result["indexes"] == ["seek"]


def test_count_growth_is_rejected_without_latency_thresholds():
    assert_constant_counts([9, 9, 9])
    with pytest.raises(AssertionError):
        assert_constant_counts([9, 10])


def test_small_payload_cannot_hide_unbounded_candidate_materialization():
    top = {"Plan": {"Plans": [
        {"Subplan Name": "CTE inventory_page_candidates", "Actual Rows": 201},
        {"Subplan Name": "CTE inventory_detail_keys", "Actual Rows": 200},
    ]}}
    assert_bounded_plan(top, 200, "list")
    top["Plan"]["Plans"][0]["Actual Rows"] = 50000
    with pytest.raises(AssertionError):
        assert_bounded_plan(top, 200, "list")


def test_one_emitted_row_does_not_make_a_catalog_scan_point_access():
    point = {"Node Type": "Index Scan", "Relation Name": "product_variants",
             "Actual Loops": 1, "Index Name": "uq_product_variants_company_id",
             "emitted_plus_filter_rows_x_loops": 1}
    assert_selective_point_scans([point])
    with pytest.raises(AssertionError):
        assert_selective_point_scans([point | {"emitted_plus_filter_rows_x_loops": 50000}])
    with pytest.raises(AssertionError):
        assert_selective_point_scans([point | {"Index Name": "ordered_catalog_scan"}])
    with pytest.raises(AssertionError):
        assert_selective_point_scans([point, {"Node Type": "Aggregate", "Actual Loops": 50000}])
