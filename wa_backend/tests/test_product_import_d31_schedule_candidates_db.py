"""Opt-in real PostgreSQL regression for D3.1 event-driven scheduling."""
from __future__ import annotations

import os
import unittest

import psycopg
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

load_dotenv()

ENABLED = os.getenv("WANASAH_D31_SCHEDULER_DB_GATE") == "1"


def _dsn(name: str) -> str:
    raw = os.environ[name]
    return make_url(raw).set(
        drivername="postgresql"
    ).render_as_string(hide_password=False)


@unittest.skipUnless(ENABLED, "Requires explicit D3.1 local PostgreSQL opt-in")
class ProductImportD31SchedulerDBTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app_dsn = _dsn("DATABASE_URL")
        cls.admin_dsn = _dsn("DATABASE_URL_MIGRATION")
        with psycopg.connect(cls.admin_dsn) as db:
            row = db.execute("""
                SELECT id FROM companies c
                WHERE NOT EXISTS (
                    SELECT 1 FROM product_import_schedule_candidates s
                    WHERE s.company_id = c.id
                )
                ORDER BY id LIMIT 1
            """).fetchone()
            if row is None:
                raise unittest.SkipTest("No idle tenant available for D3.1 gate")
            cls.company_id = int(row[0])
    def test_trigger_generation_cas_and_rls(self) -> None:
        with psycopg.connect(self.app_dsn) as db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM product_import_schedule_candidates"
                ).fetchone()[0],
                0,
            )
            db.execute(
                "SELECT set_config('app.current_tenant', %s, false)",
                (str(self.company_id),),
            )
            params = (self.company_id, 0, "D31_GATE", 1, 2, 60)
            db.execute("""
                INSERT INTO product_import_admission_rejections(
                    company_id, actor_id, code, current_value,
                    limit_value, retry_after_seconds
                ) VALUES (%s,%s,%s,%s,%s,%s)
            """, params)
            g1 = db.execute("""
                SELECT generation FROM product_import_schedule_candidates
                WHERE company_id=%s AND task_kind='capacity'
            """, (self.company_id,)).fetchone()[0]
            db.execute("""
                INSERT INTO product_import_admission_rejections(
                    company_id, actor_id, code, current_value,
                    limit_value, retry_after_seconds
                ) VALUES (%s,%s,%s,%s,%s,%s)
            """, (self.company_id, 0, "D31_GATE_2", 1, 2, 60))
            g2 = db.execute("""
                SELECT generation FROM product_import_schedule_candidates
                WHERE company_id=%s AND task_kind='capacity'
            """, (self.company_id,)).fetchone()[0]
            self.assertNotEqual(g1, g2)
            db.execute(
                "SELECT product_import_finish_schedule(%s,'capacity',%s,NULL)",
                (self.company_id, g1),
            )
            remaining = db.execute("""
                SELECT generation FROM product_import_schedule_candidates
                WHERE company_id=%s AND task_kind='capacity'
            """, (self.company_id,)).fetchone()[0]
            self.assertEqual(remaining, g2)
            db.rollback()

    def test_claim_uses_skip_locked_semantics(self) -> None:
        with psycopg.connect(self.admin_dsn) as admin:
            admin.execute("""
                INSERT INTO product_import_schedule_candidates(
                    company_id, task_kind, next_due_at
                ) VALUES (%s,'retention',TIMESTAMPTZ '1970-01-01 00:00:00+00')
            """, (self.company_id,))
            admin.commit()

        first = psycopg.connect(self.app_dsn)
        second = psycopg.connect(self.app_dsn)
        try:
            r1 = first.execute("""
                SELECT * FROM product_import_claim_schedule(
                    'retention', clock_timestamp(), 1
                )
            """).fetchall()
            self.assertEqual(r1[0][0], self.company_id)
            r2 = second.execute("""
                SELECT * FROM product_import_claim_schedule(
                    'retention', clock_timestamp(), 1000
                )
            """).fetchall()
            self.assertNotIn(self.company_id, [int(row[0]) for row in r2])
        finally:
            second.rollback()
            second.close()
            first.rollback()
            first.close()
            with psycopg.connect(self.admin_dsn) as admin:
                admin.execute("""
                    DELETE FROM product_import_schedule_candidates
                    WHERE company_id=%s AND task_kind='retention'
                """, (self.company_id,))
                admin.commit()


if __name__ == "__main__":
    unittest.main()
