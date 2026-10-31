"""Focused proof that archive navigation preserves physical InventoryLocation truth."""
from decimal import Decimal

from sqlalchemy import Column, MetaData, Table, create_engine, literal
from sqlalchemy.dialects import postgresql

from domains.inventory_archive_navigation import inventory_archive_target_query
from models import (
    InventoryBalance,
    InventoryLocation,
    InventoryLock,
    StocktakeLine,
    StocktakeSession,
)


class _AllowAllAccess:
    company_id = 1

    def allows(self, *args, **kwargs):
        return literal(True)


def _table(metadata, model, names):
    return Table(
        model.__tablename__,
        metadata,
        *(Column(name, model.__table__.c[name].type) for name in names.split()),
    )


def test_vehicle_archive_evidence_stays_on_vehicle_without_route_authority():
    metadata = MetaData()
    tables = {
        InventoryLocation: _table(
            metadata, InventoryLocation, "id company_id location_type is_active vehicle_id"
        ),
        InventoryBalance: _table(
            metadata,
            InventoryBalance,
            "id company_id location_id product_variant_id batch_id on_hand_quantity reserved_quantity",
        ),
        StocktakeSession: _table(
            metadata,
            StocktakeSession,
            "id company_id stocktake_type status location_id related_work_session_id",
        ),
        StocktakeLine: _table(
            metadata,
            StocktakeLine,
            "id company_id stocktake_session_id product_variant_id",
        ),
        InventoryLock: _table(
            metadata,
            InventoryLock,
            "id company_id stocktake_session_id product_variant_id released_at",
        ),
    }

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(
            tables[InventoryLocation].insert(),
            {
                "id": 2,
                "company_id": 1,
                "location_type": "VEHICLE",
                "is_active": True,
                "vehicle_id": 7,
            },
        )
        connection.execute(
            tables[InventoryBalance].insert(),
            {
                "id": 11,
                "company_id": 1,
                "location_id": 2,
                "product_variant_id": 101,
                "batch_id": 50,
                "on_hand_quantity": Decimal("30"),
                "reserved_quantity": Decimal("0"),
            },
        )
        connection.execute(
            tables[StocktakeSession].insert(),
            {
                "id": 30,
                "company_id": 1,
                "stocktake_type": "VEHICLE_RECON",
                "status": "COUNTING",
                "location_id": 2,
                "related_work_session_id": 80,
            },
        )
        connection.execute(
            tables[StocktakeLine].insert(),
            {
                "id": 301,
                "company_id": 1,
                "stocktake_session_id": 30,
                "product_variant_id": 101,
            },
        )
        connection.execute(
            tables[InventoryLock].insert(),
            {
                "id": 40,
                "company_id": 1,
                "stocktake_session_id": 30,
                "product_variant_id": 101,
                "released_at": None,
            },
        )

        query = inventory_archive_target_query(
            _AllowAllAccess(),
            101,
            {
                "INVENTORY_BALANCE": 11,
                "OPEN_STOCKTAKE": 30,
                "ACTIVE_INVENTORY_LOCK": 40,
            },
        )
        compiled = str(query.compile(dialect=postgresql.dialect()))
        assert "dispatch_routes" not in compiled
        assert "source_location_id" not in compiled

        rows = {
            row["code"]: dict(row)
            for row in connection.execute(query).mappings()
        }

    for code in ("INVENTORY_BALANCE", "OPEN_STOCKTAKE", "ACTIVE_INVENTORY_LOCK"):
        assert rows[code]["location_id"] == 2
        assert rows[code]["kind"] == "capability-gap"
        assert rows[code]["reason"] == "INVENTORY_SOURCE"
