from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "wa_backend"))

from database import engine


EXPECTED_DB_HEAD = "91e6b4c8d2f0"
OFFER_TABLES = (
    "offer_version_products",
    "offer_version_scopes",
    "offer_versions",
)


async def _count(conn, table: str) -> int:
    value = await conn.scalar(text(f'SELECT count(*) FROM "{table}"'))
    return int(value or 0)


async def main(delete_test_data: bool) -> int:
    try:
        async with engine.connect() as conn:
            current = await conn.scalar(text("SELECT version_num FROM alembic_version"))
            if str(current) != EXPECTED_DB_HEAD:
                raise RuntimeError(
                    f"Database head mismatch: expected {EXPECTED_DB_HEAD}, got {current}. "
                    "Refusing destructive preparation."
                )

            counts = {table: await _count(conn, table) for table in OFFER_TABLES}
            adjustment_count = await _count(conn, "sales_line_adjustments")

            print(f"ALEMBIC_HEAD={current}")
            for table, count in counts.items():
                print(f"{table}={count}")
            print(f"sales_line_adjustments={adjustment_count}")

            if adjustment_count:
                raise RuntimeError(
                    "sales_line_adjustments contains immutable evidence referencing "
                    "OfferVersion rows. Refusing to delete anything automatically. "
                    "This needs explicit evidence cleanup/reset first."
                )

            if not any(counts.values()):
                print("STAGE6H2A_DB_PREP=NO_DATA_TO_DELETE")
                return 0

            if not delete_test_data:
                print("STAGE6H2A_DB_PREP=TEST_OFFER_DATA_PRESENT")
                print(
                    "Re-run with --delete-test-offer-data only because you explicitly "
                    "confirmed these rows are disposable test data."
                )
                return 2

            # No CASCADE and no broad database reset. This deliberately deletes only
            # the pre-6H.2 offer version/configuration rows required to make the
            # clean-cut migration deterministic. Definitions are retained.
            tx = await conn.begin()
            try:
                await conn.execute(
                    text(
                        """
                        TRUNCATE TABLE
                            offer_version_products,
                            offer_version_scopes,
                            offer_versions
                        RESTART IDENTITY
                        """
                    )
                )
                await tx.commit()
            except Exception:
                await tx.rollback()
                raise

            remaining = {table: await _count(conn, table) for table in OFFER_TABLES}
            if any(remaining.values()):
                raise RuntimeError(
                    f"Offer cleanup did not reach zero rows: {remaining}"
                )

            print("STAGE6H2A_TEST_OFFER_DATA_DELETE=PASS")
            print("CASCADE_USED=NO")
            print("OFFER_DEFINITIONS_DELETED=NO")
            print("OTHER_BUSINESS_DATA_DELETED=NO")
            return 0

    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--delete-test-offer-data",
        action="store_true",
        help="Delete only disposable OfferVersion child/version rows; no CASCADE.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.delete_test_offer_data)))
