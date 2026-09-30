"""D6 permanent safety contract for test-only live performance instrumentation."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/"scripts"


class ImportD6ProfilerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner=(SCRIPTS/"run_product_import_d1_isolated_gate.py").read_text(
            encoding="utf-8"
        )
        cls.worker=(SCRIPTS/"product_import_d6_profile_worker.py").read_text(
            encoding="utf-8"
        )
        cls.child=(SCRIPTS/"product_import_d6_disposable_profile.py").read_text(
            encoding="utf-8"
        )

    def test_profiler_is_for_disposable_tenant_only(self):
        self.assertIn("WANASAH_D6_DISPOSABLE_WORKER",self.worker)
        self.assertIn("WANASAH_D1_DISPOSABLE_CHILD",self.child)
        self.assertIn("127.0.0.1:55445/d1_mix",self.child)
        self.assertIn("WANASAH_D1_LOCAL_GATE",self.runner)
        self.assertIn("D1_DEVELOPER_SOURCE_UNMODIFIED",self.runner)

    def test_server_attribution_and_sqlalchemy_roundtrip_are_separate(self):
        self.assertIn("pg_stat_statements.track=all",self.runner)
        self.assertIn("track_io_timing=on",self.runner)
        self.assertIn("before_cursor_execute",self.worker)
        self.assertIn("after_cursor_execute",self.worker)
        self.assertIn("pg_stat_statements_total_exec_seconds_delta",self.child)
        self.assertIn("sqlalchemy_driver_roundtrip_sum_seconds",self.child)
        self.assertIn("db_blocking_samples",self.child)
        self.assertIn("private_cluster_global_wal_bytes_delta",self.child)

    def test_cpu_and_memory_are_read_inside_actual_worker(self):
        self.assertIn("time.process_time()",self.worker)
        self.assertIn("psutil.Process(os.getpid())",self.worker)
        self.assertIn("worker_process_cpu_seconds",self.worker)
        self.assertIn("worker_peak_rss_mib",self.worker)
        self.assertIn("worker_process_cpu_seconds",self.child)
        self.assertIn("worker_instrumented_pid",self.child)

    def test_pricing_explain_is_bounded_and_read_only(self):
        self.assertIn("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)",self.child)
        self.assertIn("SET LOCAL statement_timeout = '3000ms'",self.child)
        self.assertIn("No published pricing revision",self.child)

    def test_business_integrity_is_rechecked_before_profile_success(self):
        self.assertIn("_assert_business_evidence(admin,job_id,expected)",self.child)
        self.assertIn("PRODUCT_IMPORT_D6_PROFILE=PASS",self.child)
        self.assertIn("WANASAH_D1_LOCAL_GATE",self.runner)
        self.assertIn("WANASAH_D1_SOURCE_ENV_FILE",self.runner)

    def test_predecessor_query_plan_probe_checks_true_and_false_equivalence(self):
        probe=(SCRIPTS/"product_import_d6_price_probe.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("WANASAH_D1_DISPOSABLE_CHILD",probe)
        self.assertIn("ORIGINAL =",probe)
        self.assertIn("CANDIDATE =",probe)
        self.assertIn("CROSS JOIN LATERAL",probe)
        self.assertIn("LIMIT 1",probe)
        self.assertIn("old_result != new_result",probe)
        self.assertIn("not original_true or not candidate_true",probe)
        self.assertIn("both_cases_boolean_parity",probe)
        self.assertIn("d6_pricing_probe(admin)",self.child)


if __name__=="__main__":
    unittest.main()
