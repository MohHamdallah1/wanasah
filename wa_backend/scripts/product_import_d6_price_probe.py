"""D6 read-only, disposable-only parity/plan probe for pricing predecessor SQL."""
from __future__ import annotations

import json
import os

if (
    os.getenv("WANASAH_D1_DISPOSABLE_CHILD") != "1"
    or os.getenv("WANASAH_D6_PROFILE") != "1"
    or "127.0.0.1:55445/d1_mix" not in os.getenv("DATABASE_URL", "")
):
    raise RuntimeError("D6 SQL plan probe is private/disposable only")

ORIGINAL = """
WITH fresh_pairs AS MATERIALIZED (
    SELECT DISTINCT product_variant_id, uom_id
    FROM price_book_entries
    WHERE company_id = %s AND price_book_id = %s AND publication_id = %s
)
SELECT EXISTS (
    SELECT 1 FROM fresh_pairs AS fresh
    WHERE EXISTS (
        SELECT 1 FROM price_book_entries AS old
        WHERE old.company_id = %s
          AND old.price_book_id = %s
          AND old.product_variant_id = fresh.product_variant_id
          AND old.uom_id = fresh.uom_id
          AND old.publication_id <> %s
          AND old.is_published IS TRUE
    )
)
"""

CANDIDATE = """
WITH fresh_pairs AS MATERIALIZED (
    SELECT DISTINCT product_variant_id, uom_id
    FROM price_book_entries
    WHERE company_id = %s AND price_book_id = %s AND publication_id = %s
)
SELECT EXISTS (
    SELECT 1
    FROM fresh_pairs AS fresh
    CROSS JOIN LATERAL (
        SELECT 1
        FROM price_book_entries AS old
        WHERE old.company_id = %s
          AND old.price_book_id = %s
          AND old.product_variant_id = fresh.product_variant_id
          AND old.uom_id = fresh.uom_id
          AND old.publication_id <> %s
          AND old.is_published IS TRUE
        LIMIT 1
    ) AS predecessor
)
"""

def run_probe(admin):
    row = admin.execute("""
      SELECT id, price_book_id FROM price_publications
      WHERE company_id=2 AND status='PUBLISHED'
      ORDER BY id DESC LIMIT 1
    """).fetchone()
    if row is None:
        raise RuntimeError("D6 no committed publication")
    pub, book = map(int, row)
    args=(2, book, pub, 2, book, pub)

    with admin.transaction():
        admin.execute("SET LOCAL statement_timeout='5000ms'")
        old_result = bool(admin.execute(ORIGINAL,args).fetchone()[0])
        new_result = bool(admin.execute(CANDIDATE,args).fetchone()[0])
        if old_result != new_result:
            raise AssertionError("D6 candidate SQL changed predecessor outcome")

        def profile(sql):
            raw=admin.execute(
                "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) "+sql,args
            ).fetchone()[0]
            if isinstance(raw,str):raw=json.loads(raw)
            plan=raw[0]
            nodes=[]
            def walk(n):
                nodes.append({
                    "node":n.get("Node Type"),
                    "relation":n.get("Relation Name"),
                    "index":n.get("Index Name"),
                    "actual_rows":n.get("Actual Rows"),
                    "loops":n.get("Actual Loops"),
                    "shared_hits":n.get("Shared Hit Blocks"),
                    "index_cond":n.get("Index Cond"),
                    "join_filter":n.get("Join Filter"),
                })
                for sub in n.get("Plans",[]):walk(sub)
            walk(plan["Plan"])
            return {
                "execution_ms":round(float(plan["Execution Time"]),3),
                "plan_shared_hits":int(plan["Plan"].get("Shared Hit Blocks",0)),
                "nodes":nodes[:12],
            }
        baseline=profile(ORIGINAL)
        alternative=profile(CANDIDATE)

        # Verify the true-predecessor branch separately using a real published
        # entry as "new" and a different publication id; only query params
        # and CTE input change, never persisted pricing authority.
        probe = admin.execute("""
            SELECT product_variant_id,uom_id
            FROM price_book_entries
            WHERE company_id=2 AND price_book_id=%s AND is_published IS TRUE
            ORDER BY id ASC LIMIT 1
        """,(book,)).fetchone()
        if probe is None:
            raise RuntimeError("D6 no published entry for parity control")
        variant,uom=map(int,probe)
        # Id 0 is not an actual publication. The true case must see at least
        # one older published row for a catalog pair.
        original_true = bool(admin.execute("""
            WITH fresh_pairs AS MATERIALIZED (
                SELECT %s::integer AS product_variant_id,
                       %s::integer AS uom_id
            )
            SELECT EXISTS (
              SELECT 1 FROM fresh_pairs fresh
              WHERE EXISTS (
                SELECT 1 FROM price_book_entries old
                WHERE old.company_id=2 AND old.price_book_id=%s
                  AND old.product_variant_id=fresh.product_variant_id
                  AND old.uom_id=fresh.uom_id
                  AND old.publication_id<>%s
                  AND old.is_published IS TRUE
              )
            )
        """,(variant,uom,book,0)).fetchone()[0])
        candidate_true=bool(admin.execute("""
            WITH fresh_pairs AS MATERIALIZED (
                SELECT %s::integer AS product_variant_id,
                       %s::integer AS uom_id
            )
            SELECT EXISTS (
              SELECT 1 FROM fresh_pairs fresh
              CROSS JOIN LATERAL (
                SELECT 1 FROM price_book_entries old
                WHERE old.company_id=2 AND old.price_book_id=%s
                  AND old.product_variant_id=fresh.product_variant_id
                  AND old.uom_id=fresh.uom_id
                  AND old.publication_id<>%s
                  AND old.is_published IS TRUE
                LIMIT 1
              ) p
            )
        """,(variant,uom,book,0)).fetchone()[0])
        if not original_true or not candidate_true:
            raise AssertionError("D6 positive-predecessor parity failed")

    return {
        "latest_publication_id":pub,
        "latest_pricebook_id":book,
        "latest_case_result":old_result,
        "positive_case_result":candidate_true,
        "both_cases_boolean_parity":True,
        "original_plan":baseline,
        "candidate_plan":alternative,
        "warning":"Synthetic private DB; read-only SQL EXPLAIN outcomes do not prove production speed or all commercial invariants.",
    }
