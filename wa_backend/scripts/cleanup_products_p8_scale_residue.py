from __future__ import annotations

import asyncio

from sqlalchemy import text

import gate_products_read_contract_p2 as p2_gate


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
                    "SELECT 1 FROM price_books AS pb "
                    "WHERE pb.company_id = c.id "
                    "AND pb.code LIKE 'P8PUB-%'"
                    ") "
                    "ORDER BY c.id ASC"
                )
            )
        ).mappings().all()

        if not candidates:
            await su.rollback()
            print(
                "PRODUCTS_P8_SCALE_RESIDUE=NONE"
            )
            print(
                "PRODUCTS_P8_SCALE_RESIDUE_CLEANUP=PASS"
            )
            return

        for candidate in candidates:
            company_id = int(
                candidate["id"]
            )

            counts = (
                await su.execute(
                    text(
                        "SELECT "
                        "(SELECT COUNT(*) "
                        " FROM price_publications "
                        " WHERE company_id = :company_id) "
                        "AS publications_total, "
                        "(SELECT COUNT(*) "
                        " FROM price_publications AS pp "
                        " JOIN price_books AS pb "
                        " ON pb.company_id = pp.company_id "
                        " AND pb.id = pp.price_book_id "
                        " WHERE pp.company_id = :company_id "
                        " AND pb.code LIKE 'P8PUB-%') "
                        "AS publications_scale, "
                        "(SELECT COUNT(*) "
                        " FROM price_book_entries "
                        " WHERE company_id = :company_id) "
                        "AS entries_total, "
                        "(SELECT COUNT(*) "
                        " FROM price_book_assignments "
                        " WHERE company_id = :company_id) "
                        "AS assignments_total"
                    ),
                    {
                        "company_id": company_id,
                    },
                )
            ).mappings().one()

            total_publications = int(
                counts[
                    "publications_total"
                ]
            )
            scale_publications = int(
                counts[
                    "publications_scale"
                ]
            )
            entries_total = int(
                counts["entries_total"]
            )
            assignments_total = int(
                counts[
                    "assignments_total"
                ]
            )

            print(
                "SCALE_RESIDUE_CANDIDATE "
                f"company_id={company_id} "
                f"company_code={candidate['company_code']} "
                f"publications_total={total_publications} "
                f"publications_scale={scale_publications} "
                f"entries={entries_total} "
                f"assignments={assignments_total}"
            )

            if (
                total_publications <= 0
                or total_publications
                != scale_publications
                or entries_total != 0
                or assignments_total != 0
            ):
                raise RuntimeError(
                    "Synthetic P8 residue safety check failed; refusing cleanup."
                )

            companions = (
                await su.execute(
                    text(
                        "SELECT id "
                        "FROM companies "
                        "WHERE name = 'P2 Read Contract Gate B' "
                        "AND company_code LIKE 'P2READ-%' "
                        "AND created_at BETWEEN "
                        ":created_at - INTERVAL '10 seconds' "
                        "AND :created_at + INTERVAL '10 seconds'"
                    ),
                    {
                        "created_at": candidate[
                            "created_at"
                        ],
                    },
                )
            ).scalars().all()

            await su.execute(
                text(
                    "ALTER TABLE price_publications "
                    "DISABLE TRIGGER "
                    "trg_price_publication_history_guard"
                )
            )
            await su.execute(
                text(
                    "DELETE FROM price_publications AS pp "
                    "USING price_books AS pb "
                    "WHERE pp.company_id = :company_id "
                    "AND pb.company_id = pp.company_id "
                    "AND pb.id = pp.price_book_id "
                    "AND pb.code LIKE 'P8PUB-%'"
                ),
                {
                    "company_id": company_id,
                },
            )
            await su.execute(
                text(
                    "ALTER TABLE price_publications "
                    "ENABLE TRIGGER "
                    "trg_price_publication_history_guard"
                )
            )

            await su.execute(
                text(
                    "DELETE FROM companies "
                    "WHERE id = :company_id"
                ),
                {
                    "company_id": company_id,
                },
            )

            for companion_id in companions:
                await su.execute(
                    text(
                        "DELETE FROM companies "
                        "WHERE id = :company_id"
                    ),
                    {
                        "company_id": int(
                            companion_id
                        ),
                    },
                )

            recovered += 1

        await su.execute(
            text(
                "ANALYZE price_publications"
            )
        )
        await su.commit()

    await p2_gate.engine_su.dispose()
    await p2_gate.engine_app.dispose()

    print(
        "PRODUCTS_P8_SCALE_RESIDUE_RECOVERED="
        f"{recovered}"
    )
    print(
        "PRODUCTS_P8_SCALE_RESIDUE_CLEANUP=PASS"
    )


if __name__ == "__main__":
    asyncio.run(main())
