"""Inventory-owned immutable document evidence, independent of live Supplier data.

One snapshot per posted movement. Legacy movements have no row and stay readable.
No stock/cost authority is introduced; movements are produced by the unified engine.
"""
from sqlalchemy import Column, ForeignKeyConstraint, Integer, String, Uuid
from models import Base
from domains.suppliers.contracts import SupplierSnapshot


class InventorySupplierEvidence(Base):
    __tablename__ = "inventory_supplier_evidence"
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "movement_id"], ["inventory_movements.company_id", "inventory_movements.id"],
                             name="fk_supplier_evidence_movement", ondelete="RESTRICT"),
        ForeignKeyConstraint(["company_id", "supplier_id"], ["suppliers.company_id", "suppliers.id"],
                             name="fk_supplier_evidence_supplier", ondelete="RESTRICT"),
    )
    company_id = Column(Integer, primary_key=True)
    movement_id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, nullable=False)
    supplier_name = Column(String(300), nullable=False)
    supplier_code = Column(String(50), nullable=True)
    request_id = Column(Uuid, nullable=False)


def record_supplier_evidence(db, *, company_id, movement_ids, supplier: SupplierSnapshot, request_id):
    db.add_all([InventorySupplierEvidence(
        company_id=company_id, movement_id=movement_id, supplier_id=supplier.id,
        supplier_name=supplier.name, supplier_code=supplier.code, request_id=request_id,
    ) for movement_id in movement_ids])
