from __future__ import annotations

import asyncio

from sqlalchemy import text

import gate_products_read_contract_p2 as p2_gate
from gate_products_p8_concurrency_idempotency import (
    cleanup_pricing_history,
    cleanup_release_evidence,
)


async def main() -> None:
    recovered = 0

    async with p2_gate.SessionSU() as su:
        await su.begin()
        candidates = (
            await su.execute(
                text(
                    "SELECT c.id, c.company_code, c.created_at "
                    "FROM companies AS c "
                    "WHERE c.name = 'P2 Read Contract Gate A' "
                    "AND c.company_code LIKE 'P2READ-%' "
                    "AND EXISTS ("
                    "SELECT 1 FROM drivers AS d "
                    "WHERE d.company_id = c.id "
                    "AND d.full_name = 'P8 Concurrency Actor'"
                    ") "
                    "AND EXISTS ("
                    "SELECT 1 "
                    "FROM product_variants AS pv "
                    "WHERE pv.company_id = c.id "
                    "AND pv.name LIKE 'P8 Idempotent Product %'"
                    ") "
                    "ORDER BY c.id ASC"
                )
            )
        ).mappings().all()
        await su.rollback()

    if not candidates:
        print(
            "PRODUCTS_P8_CONCURRENCY_RESIDUE=NONE"
        )
        print(
            "PRODUCTS_P8_CONCURRENCY_RESIDUE_CLEANUP=PASS"
        )
        await p2_gate.engine_app.dispose()
        await p2_gate.engine_su.dispose()
        return

    for candidate in candidates:
        company_id = int(
            candidate["id"]
        )

        async with p2_gate.SessionSU() as su:
            await su.begin()
            companions = (
                await su.execute(
                    text(
                        "SELECT id, company_code "
                        "FROM companies "
                        "WHERE name = 'P2 Read Contract Gate B' "
                        "AND company_code LIKE 'P2READ-%' "
                        "AND created_at BETWEEN "
                        "CAST(:created_at AS timestamp without time zone) "
                        "- INTERVAL '10 seconds' "
                        "AND CAST(:created_at AS timestamp without time zone) "
                        "+ INTERVAL '10 seconds' "
                        "ORDER BY ABS(EXTRACT(EPOCH FROM "
                        "(created_at - CAST(:created_at AS timestamp without time zone)))) ASC, "
                        "id ASC"
                    ),
                    {
                        "created_at":
                            candidate[
                                "created_at"
                            ],
                    },
                )
            ).mappings().all()
            await su.rollback()

        if len(companions) != 1:
            raise RuntimeError(
                "Synthetic P8 concurrency residue companion is ambiguous; refusing cleanup."
            )

        foreign_company_id = int(
            companions[0]["id"]
        )
        company_ids = [
            company_id,
            foreign_company_id,
        ]

        print(
            "CONCURRENCY_RESIDUE_CANDIDATE "
            f"company_id={company_id} "
            f"company_code={candidate['company_code']} "
            f"foreign_company_id={foreign_company_id} "
            f"foreign_company_code={companions[0]['company_code']}"
        )

        await cleanup_pricing_history(
            company_ids
        )
        await cleanup_release_evidence(
            company_ids
        )

        cleanup_ok, cleanup_detail = (
            await p2_gate.cleanup(
                {
                    "company_id":
                        company_id,
                    "foreign_company_id":
                        foreign_company_id,
                }
            )
        )
        if not cleanup_ok:
            raise RuntimeError(
                "Synthetic P8 concurrency residue cleanup failed: "
                + cleanup_detail
            )

        recovered += 1

    async with p2_gate.SessionSU() as su:
        await su.begin()
        remaining = int(
            (
                await su.execute(
                    text(
                        "SELECT COUNT(*) "
                        "FROM companies AS c "
                        "WHERE c.name = 'P2 Read Contract Gate A' "
                        "AND c.company_code LIKE 'P2READ-%' "
                        "AND EXISTS ("
                        "SELECT 1 FROM drivers AS d "
                        "WHERE d.company_id = c.id "
                        "AND d.full_name = 'P8 Concurrency Actor'"
                        ")"
                    )
                )
            ).scalar_one()
        )
        await su.rollback()

    if remaining != 0:
        raise RuntimeError(
            "Synthetic P8 concurrency residue remains after cleanup."
        )

    await p2_gate.engine_app.dispose()
    await p2_gate.engine_su.dispose()

    print(
        "PRODUCTS_P8_CONCURRENCY_RESIDUE_RECOVERED="
        f"{recovered}"
    )
    print(
        "PRODUCTS_P8_CONCURRENCY_RESIDUE_CLEANUP=PASS"
    )


if __name__ == "__main__":
    asyncio.run(main())
