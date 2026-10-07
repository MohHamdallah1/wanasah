"""Supplier commands: current authorization, durable replay, locking and audit."""
import hashlib
import json
from sqlalchemy.exc import IntegrityError
from models import utc_now
from product_lifecycle import record_domain_event
from services import InventoryMutationError, begin_idempotent_operation, complete_idempotent_operation
from .models import Supplier
from .public import require_supplier_permission
from .errors import fail
from .repository import load_supplier, supplier_view


async def mutate_supplier(db, actor, payload, *, supplier_id=None, state=False):
    await require_supplier_permission(db, actor, "supplier.manage")
    body = payload.model_dump(mode="json", exclude={"request_id"})
    canonical = json.dumps({"supplier_id": supplier_id, **body}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    operation = "SUPPLIER_CREATE" if supplier_id is None else ("SUPPLIER_STATE" if state else "SUPPLIER_UPDATE")
    try:
        idem, replay = await begin_idempotent_operation(
            db, company_id=actor.company_id, actor_id=actor.id, operation=operation,
            request_id=str(payload.request_id), request_hash=hashlib.sha256(canonical.encode()).hexdigest())
        if replay is not None:
            await db.rollback()
            return replay
        before = None
        if supplier_id is None:
            row = Supplier(company_id=actor.company_id, created_by=actor.id, updated_by=actor.id, **body)
            db.add(row)
        else:
            row = await load_supplier(db, actor.company_id, supplier_id, lock=True)
            before = supplier_view(row)
            if row.version != payload.expected_version:
                fail(409, "SUPPLIER_VERSION_CONFLICT", "Supplier was changed. Refresh before editing.")
            for field, value in body.items():
                if field != "expected_version":
                    setattr(row, field, value)
            row.version += 1
            row.updated_by = actor.id
            row.updated_at = utc_now()
        await db.flush()
        response = supplier_view(row)
        record_domain_event(db, company_id=actor.company_id, actor_id=actor.id,
                            request_id=payload.request_id, event_type=operation,
                            entity_type="Supplier", entity_id=row.id,
                            reason=operation,
                            before=before, after=response, emit_outbox=True)
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response
    except InventoryMutationError:
        await db.rollback()
        fail(409, "SUPPLIER_REQUEST_CONFLICT", "This request identity was already used for a different command.")
    except IntegrityError:
        await db.rollback()
        fail(409, "SUPPLIER_DATA_CONFLICT", "Supplier code is already used or the record changed concurrently.")
    except Exception:
        await db.rollback()
        raise
