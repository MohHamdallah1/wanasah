"""Supplier identity persistence, owned exclusively by Supplier Master."""
from sqlalchemy import (Boolean, CheckConstraint, Column, Computed, DateTime,
                        ForeignKey, ForeignKeyConstraint, Index, Integer, String,
                        UniqueConstraint, text)
from models import Base, utc_now


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_suppliers_company_id"),
        UniqueConstraint("company_id", "code", name="uq_suppliers_company_code"),
        ForeignKeyConstraint(["company_id", "created_by"], ["drivers.company_id", "drivers.id"],
                             ondelete="RESTRICT", name="fk_suppliers_tenant_creator"),
        ForeignKeyConstraint(["company_id", "updated_by"], ["drivers.company_id", "drivers.id"],
                             ondelete="RESTRICT", name="fk_suppliers_tenant_editor"),
        CheckConstraint("length(trim(name)) > 0", name="supplier_name_not_blank"),
        CheckConstraint("version > 0", name="supplier_version_positive"),
        Index("ix_suppliers_company_active_id", "company_id", "is_active", "id"),
        Index("ix_suppliers_search", "search_text", postgresql_using="gin",
              postgresql_ops={"search_text": "gin_trgm_ops"}),
    )
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    name = Column(String(300), nullable=False)
    code = Column(String(50), nullable=True)
    contact_person = Column(String(150), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(254), nullable=True)
    address = Column(String(1000), nullable=True)
    notes = Column(String(4000), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_by = Column(Integer, nullable=False)
    updated_by = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now,
                        server_default=text("CURRENT_TIMESTAMP"))
    search_text = Column(String, Computed(
        "lower(name || ' ' || coalesce(code, '') || ' ' || coalesce(contact_person, '') "
        "|| ' ' || coalesce(phone, '') || ' ' || coalesce(email, ''))", persisted=True))
