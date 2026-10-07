"""Identity seed for existing explicitly opted-in synthetic C2 database gates."""
from domains.suppliers.models import Supplier


async def seed_receipt_supplier(db, actor):
    supplier = Supplier(company_id=actor.company_id, name="C2 synthetic receipt supplier",
                        created_by=actor.id, updated_by=actor.id, is_active=True)
    db.add(supplier)
    await db.flush()
    return int(supplier.id)
