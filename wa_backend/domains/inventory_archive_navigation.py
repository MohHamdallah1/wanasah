"""Public Inventory read projection for Catalog archive navigation.

Resolve only the representative IDs returned by archive authority. These are
navigation hints, never command capabilities; every destination reads again.
No lifecycle decision, lock, write, or inferred cleanup operation belongs here.
"""
from sqlalchemy import Integer, String, and_, case, cast, literal, or_, select, union_all
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from product_lifecycle import product_location_delete_blockers
from models import (
    InventoryBalance, InventoryLocation, InventoryLock,
    InventoryTransferHeader, InventoryTransferLine, ProductLocation, StocktakeLine, StocktakeSession,
)


def _archive_access(
    access: BackofficeCapabilityAccess,
) -> BackofficeCapabilityAccess:
    return access


def inventory_archive_target_query(access, variant_id, samples):
    """One bounded query for at most five samples, filtered before projection."""
    company = access.company_id
    location = InventoryLocation
    statements = []

    def columns(code, kind, operation_id, location_id, batch_id=None, reference=None, reason=None):
        return (
            literal(code).label("code"), (literal(kind) if isinstance(kind, str) else kind).label("kind"),
            operation_id.label("operation_id"), location_id.label("location_id"),
            (batch_id if batch_id is not None else cast(literal(None), Integer)).label("batch_id"),
            (reference if reference is not None else cast(literal(None), String)).label("reference"),
            (reason if reason is not None else cast(literal(None), String)).label("reason"),
        )

    if samples.get("INVENTORY_BALANCE"):
        balance = InventoryBalance
        # Archive navigation must preserve the actual physical InventoryLocation.
        # The current batch workspace can open Warehouse custody only; Vehicle
        # custody therefore remains explicit evidence and fails closed as a
        # navigation capability gap instead of inventing a Warehouse shell.
        warehouse_supported = and_(
            location.is_active.is_(True),
            location.location_type == "WAREHOUSE",
        )
        statements.append(select(
            *columns(
                "INVENTORY_BALANCE",
                case((warehouse_supported, "batch"), else_="capability-gap"),
                balance.id,
                location.id,
                balance.batch_id,
                reason=case(
                    (warehouse_supported, cast(literal(None), String)),
                    else_="INVENTORY_SOURCE",
                ),
            )
        ).join(
            location, and_(
                location.company_id == balance.company_id,
                location.id == balance.location_id,
            ),
        ).where(
            balance.company_id == company,
            balance.product_variant_id == variant_id,
            balance.id == samples["INVENTORY_BALANCE"],
            or_(balance.on_hand_quantity != 0, balance.reserved_quantity != 0),
            location.location_type.in_(("WAREHOUSE", "VEHICLE")),
            access.allows("inventory.read", location.id),
            access.allows("catalog.read", any_location=True),
            or_(
                location.location_type == "VEHICLE",
                access.allows("location.read", location.id),
            ),
        ))

    if samples.get("OPEN_TRANSFER"):
        header = InventoryTransferHeader
        source_action = and_(access.allows("transfer.read", header.source_location_id),
                             access.allows("location.read", header.source_location_id),
                             access.allows("transfer.cancel", header.source_location_id))
        destination_action = and_(access.allows("transfer.read", header.destination_location_id),
                                  access.allows("location.read", header.destination_location_id),
                                  access.allows(("transfer.receive", "transfer.reject"), header.destination_location_id))
        source_read = and_(access.allows("transfer.read", header.source_location_id), access.allows("location.read", header.source_location_id))
        location_id = case((source_action, header.source_location_id), (destination_action, header.destination_location_id),
                           (source_read, header.source_location_id), else_=header.destination_location_id)
        in_transit = header.status == "IN_TRANSIT"
        statements.append(select(*columns("OPEN_TRANSFER", case((in_transit, "transfer"), else_="capability-gap"), header.id, location_id, reference=header.reference_number,
                                         reason=case((in_transit, cast(literal(None), String)), else_="TRANSIT_STATE"))).join(
            location, and_(location.company_id == header.company_id, location.id == location_id),
        ).where(
            header.company_id == company, header.id == samples["OPEN_TRANSFER"],
            # The existing Transfers UI has executable actions only IN_TRANSIT.
            header.workflow_type == "TRANSIT", header.status.in_(("DRAFT", "PENDING", "IN_TRANSIT", "ACCEPTED")),
            location.location_type.in_(("WAREHOUSE", "VEHICLE", "SCRAP")),
            access.allows("transfer.read", location.id), access.allows("location.read", location.id),
            or_(~in_transit, source_action, destination_action),
            select(1).where(InventoryTransferLine.company_id == company,
                            InventoryTransferLine.transfer_header_id == header.id,
                            InventoryTransferLine.product_variant_id == variant_id).correlate(header).exists(),
        ))

    for code in ("OPEN_STOCKTAKE", "ACTIVE_INVENTORY_LOCK"):
        if not samples.get(code):
            continue
        session = StocktakeSession
        vehicle_recon = session.stocktake_type == "VEHICLE_RECON"
        unsupported_state = session.status.in_(("DRAFT", "APPROVED"))
        navigation_gap = or_(vehicle_recon, unsupported_state)
        statement = select(
            *columns(
                code,
                case((navigation_gap, "capability-gap"), else_="stocktake"),
                session.id,
                session.location_id,
                reason=case(
                    (vehicle_recon, "INVENTORY_SOURCE"),
                    (unsupported_state, "STOCKTAKE_STATE"),
                    else_=cast(literal(None), String),
                ),
            )
        ).select_from(session).join(
            location,
            and_(
                location.company_id == session.company_id,
                location.id == session.location_id,
            ),
        ).where(
            session.company_id == company,
            session.status.in_(("DRAFT", "COUNTING", "PENDING_REVIEW", "RECOUNT_REQUIRED", "APPROVED")),
            location.is_active.is_(True),
            or_(
                and_(
                    vehicle_recon,
                    location.location_type == "VEHICLE",
                ),
                and_(
                    session.stocktake_type != "VEHICLE_RECON",
                    location.location_type == "WAREHOUSE",
                ),
            ),
            access.allows("stocktake.read", session.location_id),
            or_(
                unsupported_state,
                and_(
                    session.status.in_(("COUNTING", "RECOUNT_REQUIRED")),
                    access.allows("stocktake.count", session.location_id),
                ),
                and_(
                    session.status == "PENDING_REVIEW",
                    access.allows("stocktake.review", session.location_id),
                ),
            ),
        )
        if code == "OPEN_STOCKTAKE":
            statement = statement.where(session.id == samples[code], select(1).where(
                StocktakeLine.company_id == company, StocktakeLine.stocktake_session_id == session.id,
                StocktakeLine.product_variant_id == variant_id,
            ).correlate(session).exists())
        else:
            lock = InventoryLock
            statement = statement.join(lock, and_(lock.company_id == session.company_id, lock.stocktake_session_id == session.id)).where(
                lock.company_id == company, lock.id == samples[code],
                lock.product_variant_id == variant_id, lock.released_at.is_(None),
            )
        statements.append(statement)

    if samples.get("PRODUCT_LOCATION"):
        assignment = ProductLocation
        statements.append(select(*columns("PRODUCT_LOCATION", "product-location", assignment.id, assignment.location_id)).join(
            location, and_(location.company_id == assignment.company_id, location.id == assignment.location_id),
        ).where(
            assignment.company_id == company, assignment.id == samples["PRODUCT_LOCATION"],
            assignment.product_variant_id == variant_id,
            access.allows("product_location.read", location.id), access.allows("product_location.manage", location.id),
            access.allows("location.read", location.id), access.allows("catalog.read", any_location=True),
        ))
    return union_all(*statements) if statements else None


async def inventory_archive_targets(db, access: BackofficeCapabilityAccess, variant_id, blockers):
    access = _archive_access(access)
    samples = {row["code"]: row["sample_id"] for row in blockers}
    query = inventory_archive_target_query(access, variant_id, samples)
    if query is None:
        return {}
    targets = {row["code"]: {key: value for key, value in row.items() if key != "code"}
               for row in (await db.execute(query)).mappings()}
    assignment = targets.get("PRODUCT_LOCATION")
    if assignment and await product_location_delete_blockers(db, access.company_id, assignment["location_id"], variant_id):
        # Reuse the deletion guard rather than promising an impossible removal.
        targets["PRODUCT_LOCATION"] = {"kind": "capability-gap", "reason": "PRODUCT_LOCATION_REFERENCES"}
    return targets
