"""Read-only integrity proofs reused by D1/D4 disposable import gates."""
from __future__ import annotations

import psycopg


def _assert_business_evidence(
    admin: psycopg.Connection,
    job_id: str,
    expected_imported: int,
    *,
    company_id: int = 2,
) -> dict[str, int]:
    rows = admin.execute(
        """
        SELECT
          count(*) FILTER (WHERE status='IMPORTED'),
          count(DISTINCT product_variant_id) FILTER (WHERE status='IMPORTED'),
          count(*) FILTER (WHERE status='INVALID'),
          count(*) FILTER (WHERE status='IMPORT_FAILED')
        FROM product_import_rows
        WHERE company_id=%s AND job_id=%s
        """,
        (company_id, job_id),
    ).fetchone()
    imported, distinct_variants, invalid, import_failed = map(int, rows)
    if imported != expected_imported or distinct_variants != expected_imported:
        raise RuntimeError(
            f"Product Import imported lineage mismatch imported={imported} "
            f"distinct={distinct_variants} expected={expected_imported}"
        )
    ids = [
        int(row[0])
        for row in admin.execute(
            """
            SELECT product_variant_id
            FROM product_import_rows
            WHERE company_id=%s AND job_id=%s AND status='IMPORTED'
            ORDER BY row_number
            """,
            (company_id, job_id),
        ).fetchall()
    ]
    variant_count = int(admin.execute(
        "SELECT count(*) FROM product_variants WHERE company_id=%s AND id=ANY(%s)",
        (company_id, ids),
    ).fetchone()[0])
    if variant_count != expected_imported:
        raise RuntimeError(f"Product Import ProductVariant count mismatch: {variant_count}")

    price_variants = int(admin.execute(
        """
        SELECT count(DISTINCT product_variant_id)
        FROM price_book_entries
        WHERE company_id=%s AND product_variant_id=ANY(%s)
        """,
        (company_id, ids),
    ).fetchone()[0])
    price_duplicates = int(admin.execute(
        """
        SELECT count(*) FROM (
          SELECT product_variant_id,uom_id,lower(effectivity),count(*) AS n
          FROM price_book_entries
          WHERE company_id=%s AND product_variant_id=ANY(%s)
          GROUP BY product_variant_id,uom_id,lower(effectivity)
          HAVING count(*) > 1
        ) AS duplicates
        """,
        (company_id, ids),
    ).fetchone()[0])
    if price_variants != expected_imported or price_duplicates:
        raise RuntimeError(
            f"Product Import price evidence mismatch variants={price_variants} "
            f"duplicates={price_duplicates}"
        )

    text_ids = [str(value) for value in ids]
    audit = admin.execute(
        """
        SELECT count(*),count(DISTINCT entity_id)
        FROM domain_audit_events
        WHERE company_id=%s AND entity_type='ProductVariant'
          AND entity_id=ANY(%s)
        """,
        (company_id, text_ids),
    ).fetchone()
    outbox = admin.execute(
        """
        SELECT count(*),count(DISTINCT aggregate_id)
        FROM transactional_outbox
        WHERE company_id=%s AND aggregate_type='ProductVariant'
          AND aggregate_id=ANY(%s)
        """,
        (company_id, text_ids),
    ).fetchone()
    if tuple(map(int, audit)) != (expected_imported, expected_imported):
        raise RuntimeError(f"Product Import audit duplication/missing evidence: {audit}")
    if tuple(map(int, outbox)) != (expected_imported, expected_imported):
        raise RuntimeError(f"Product Import outbox duplication/missing evidence: {outbox}")

    return {
        "imported": imported,
        "invalid": invalid,
        "import_failed": import_failed,
        "price_variants": price_variants,
        "audit": int(audit[0]),
        "outbox": int(outbox[0]),
    }
