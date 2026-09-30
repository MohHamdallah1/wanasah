"""D7 permanent safeguards for the opt-in, disposable mixed-load harness."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/"scripts"
DOC=ROOT.parent/"docs/architecture/PRODUCT_IMPORT_D7_ACCEPTANCE_2026-09-30.md"


class D7LoadGateContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main=(SCRIPTS/"product_import_d7_burst_child.py").read_text(encoding="utf-8")
        cls.runner=(SCRIPTS/"run_product_import_d1_isolated_gate.py").read_text(encoding="utf-8")
        cls.docs=DOC.read_text(encoding="utf-8")

    def test_real_burst_composition_exactly_1000(self):
        source=ast.parse(self.main)
        expr=None
        for stmt in source.body:
            if not isinstance(stmt,ast.Assign):continue
            if not any(isinstance(t,ast.Name) and t.id=="COUNTS" for t in stmt.targets):
                continue
            expr=stmt.value
            break
        self.assertIsInstance(expr,ast.Dict)
        groups={}
        for key,val in zip(expr.keys,expr.values):
            group=ast.literal_eval(key)
            if isinstance(val,ast.Name):
                self.assertEqual(val.id,"S")
                weight=1
            else:
                self.assertIsInstance(val,ast.BinOp)
                self.assertIsInstance(val.op,ast.Mult)
                self.assertIsInstance(val.left,ast.Constant)
                self.assertIsInstance(val.right,ast.Name)
                self.assertEqual(val.right.id,"S")
                weight=int(val.left.value)
            groups[group]=weight*10
        self.assertEqual(groups,{
            "catalog":580,
            "owned_status":200,
            "foreign_status":60,
            "sale":30,
            "inbound":40,
            "route":30,
            "import":20,
            "import_replay":20,
            "sale_replay":10,
            "inbound_replay":10,
        })
        self.assertEqual(sum(groups.values()),1000)
        self.assertIn("asyncio.create_task(run_one(spec)) for spec in specs",self.main)
        self.assertIn("barrier.set()",self.main)
        self.assertIn('os.getenv("WANASAH_D7_CLIENT_INFLIGHT","10")',self.main)
        self.assertIn("ADMISSION_LIMIT>100",self.main)
        self.assertIn("ADMISSION_LIMIT>N",self.main)

    def test_disposable_guard_and_original_source_read_only(self):
        self.assertIn("WANASAH_D7_DISPOSABLE_CHILD",self.main)
        self.assertIn("127.0.0.1:55445/d1_mix",self.main)
        self.assertIn("WANASAH_D1_LOCAL_GATE",self.runner)
        self.assertIn("base._assert_source_url()",self.runner)
        self.assertIn("base._verify_source_still_empty(source)",self.runner)
        self.assertIn("clone_second_synthetic_tenant",self.runner)
        self.assertIn("D1_PRIVATE_POSTGRES_REMOVED",self.runner)
        self.assertIn("sum((bool(matrix),bool(d2_lock),bool(d6_profile),bool(d7_burst)))",self.runner)

    def test_policy_denial_is_not_silently_counted_as_a_successful_upload(self):
        self.assertIn("PRODUCT_IMPORT_USER_RATE_LIMITED",self.main)
        self.assertIn("retry-after",self.main)
        self.assertIn("product_import_admission_rejections",self.main)
        self.assertIn("policy_denied_unique",self.main)
        self.assertIn("replay_first_admitted",self.main)
        self.assertIn("denial_rows!=rejected_attempts",self.main)
        self.assertIn("max_rolling_admissions",self.main)
        self.assertIn("Product Import rolling quota violated",self.main)
        self.assertIn("request(\"import\",company,index,None)",self.main)
        self.assertIn("eventual_new_imports_admitted_after_window",self.main)
        self.assertNotIn("PRODUCT_IMPORT_MAX_UPLOADS_PER_USER_WINDOW",self.runner)
        self.assertIn("NEVER raise or",self.docs)

    def test_true_http_business_authority_is_verified_not_just_counted(self):
        for endpoint in (
            "/simple-products?limit=10",
            "/simple-products/imports",
            "/warehouse/inbound",
            "/dispatch/route",
            "/visits/",
        ):
            self.assertIn(endpoint,self.main)
        for contract in (
            "inventory_cost_events",
            "inventory_movements",
            "route_commercial_contexts",
            "domain_audit_events",
            "transactional_outbox",
            "price_book_entries",
            "product_import_rows",
            "negative inventory balance",
        ):
            if contract=="negative inventory balance":
                self.assertIn("on_hand_quantity<0",self.main)
            else:
                self.assertIn(contract,self.main)
        self.assertIn("await tenant_rls_proof()",self.main)
        self.assertIn("foreign_status",self.main)

    def test_load_does_not_bypass_worker_or_database_limits(self):
        self.assertIn('"--role",role',self.main)
        self.assertIn('("control","maintenance","execution")',self.main)
        self.assertIn("same_company_double",self.main)
        self.assertIn("cross_overlap",self.main)
        self.assertIn("max_import_doing>2",self.main)
        self.assertIn("max_app_conns>28",self.main)
        self.assertIn("max_total_conns>60",self.main)
        self.assertIn("SLO_READ_P95_MS=3000",self.main)
        self.assertIn("SLO_WRITE_P95_MS=5000",self.main)
        self.assertIn("SLO_TOTAL_BURST_S=120",self.main)
        self.assertIn("production-like staging",self.docs)
        self.assertIn("Do **not** sign off V1",self.docs)
        self.assertIn("sampled_db_blocker_breakdown",self.main)
        self.assertIn("longest_observed_import_queue_age_seconds",self.main)
        self.assertIn("arrival_to_result_p95_ms",self.main)
        self.assertIn("client_queue_wait_p99_ms",self.main)
        self.assertIn("max_blocked_query_active_age_ms",self.main)
        self.assertIn("str(ADMISSION_LIMIT)",self.main)


if __name__=="__main__":
    unittest.main()
