"""M01 persistence only: historical links never confer live assignment authority."""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKeyConstraint,
    Index, Integer, String, UniqueConstraint, text,
)
from models import Base, utc_now


class DispatchRouteExecutionPeriod(Base):
    __tablename__ = "dispatch_route_execution_periods"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_route_period_tenant_id"),
        UniqueConstraint("company_id", "route_id", "context_revision", name="uq_route_period_revision"),
        UniqueConstraint("company_id", "id", "work_session_id", "driver_id",
                         "vehicle_location_id", "context_revision", name="uq_route_period_visit_context"),
        ForeignKeyConstraint(["company_id", "route_id"],
                             ["dispatch_routes.company_id", "dispatch_routes.id"],
                             ondelete="RESTRICT", name="fk_route_period_tenant_route"),
        ForeignKeyConstraint(["company_id", "work_session_id", "driver_id"],
                             ["work_sessions.company_id", "work_sessions.id", "work_sessions.driver_id"],
                             ondelete="RESTRICT", name="fk_route_period_tenant_session_driver"),
        ForeignKeyConstraint(["company_id", "driver_id"],
                             ["drivers.company_id", "drivers.id"],
                             ondelete="RESTRICT", name="fk_route_period_tenant_driver"),
        ForeignKeyConstraint(["company_id", "field_representative_id"],
                             ["field_representatives.company_id", "field_representatives.id"],
                             ondelete="RESTRICT", name="fk_route_period_tenant_representative"),
        ForeignKeyConstraint(["company_id", "vehicle_id"],
                             ["vehicles.company_id", "vehicles.id"],
                             ondelete="RESTRICT", name="fk_route_period_tenant_vehicle"),
        ForeignKeyConstraint(["company_id", "vehicle_location_id", "vehicle_id"],
                             ["inventory_locations.company_id", "inventory_locations.id",
                              "inventory_locations.vehicle_id"],
                             ondelete="RESTRICT", name="fk_route_period_tenant_vehicle_location"),
        ForeignKeyConstraint(["company_id", "commercial_context_id"],
                             ["route_commercial_contexts.company_id", "route_commercial_contexts.id"],
                             ondelete="RESTRICT", name="fk_route_period_tenant_commercial"),
        ForeignKeyConstraint(["company_id", "started_by_principal_id"],
                             ["company_principals.company_id", "company_principals.id"],
                             ondelete="RESTRICT", name="fk_route_period_tenant_starter"),
        ForeignKeyConstraint(["company_id", "ended_by_principal_id"],
                             ["company_principals.company_id", "company_principals.id"],
                             ondelete="RESTRICT", name="fk_route_period_tenant_ender"),
        CheckConstraint("state IN ('PLANNED','ACTIVE','CLOSED','HISTORICAL','NEEDS_REVIEW')",
                        name="route_period_state"),
        CheckConstraint("context_revision > 0", name="route_period_revision_positive"),
        CheckConstraint("ended_at IS NULL OR started_at IS NOT NULL AND ended_at >= started_at",
                        name="route_period_time_order"),
        CheckConstraint(
            "(state = 'CLOSED' AND ended_at IS NOT NULL) OR "
            "(state IN ('PLANNED','ACTIVE') AND ended_at IS NULL) OR "
            "state IN ('HISTORICAL','NEEDS_REVIEW')",
            name="route_period_state_end"),
        CheckConstraint(
            "state NOT IN ('PLANNED','ACTIVE','CLOSED') OR "
            "(field_representative_id IS NOT NULL AND vehicle_location_id IS NOT NULL "
            "AND started_at IS NOT NULL AND started_by_principal_id IS NOT NULL "
            "AND request_id IS NOT NULL AND payload_hash IS NOT NULL)",
            name="route_period_canonical_evidence"),
        Index("uq_route_period_live_route", "company_id", "route_id", unique=True,
              postgresql_where=text("ended_at IS NULL AND state IN ('PLANNED','ACTIVE')")),
        Index("uq_route_period_live_driver", "company_id", "driver_id", unique=True,
              postgresql_where=text("ended_at IS NULL AND state IN ('PLANNED','ACTIVE')")),
        Index("uq_route_period_live_vehicle", "company_id", "vehicle_id", unique=True,
              postgresql_where=text("ended_at IS NULL AND state IN ('PLANNED','ACTIVE')")),
        Index("uq_route_period_request", "company_id", "request_id", unique=True,
              postgresql_where=text("request_id IS NOT NULL")),
        Index("ix_route_period_session", "company_id", "work_session_id", "id"),
        Index("ix_route_period_route_history", "company_id", "route_id", "id"),
    )
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(Integer, nullable=False)
    route_id = Column(Integer, nullable=False)
    work_session_id = Column(Integer, nullable=True)
    driver_id = Column(Integer, nullable=False)
    field_representative_id = Column(Integer, nullable=True)
    vehicle_id = Column(Integer, nullable=False)
    vehicle_location_id = Column(Integer, nullable=True)
    commercial_context_id = Column(Integer, nullable=True)
    state = Column(String(20), nullable=False)
    context_revision = Column(BigInteger, nullable=False)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    started_by_principal_id = Column(Integer, nullable=True)
    ended_by_principal_id = Column(Integer, nullable=True)
    reason = Column(String(120), nullable=True)
    review_reason = Column(String(120), nullable=True)
    evidence_origin = Column(String(24), nullable=False, default="CANONICAL", server_default="CANONICAL")
    request_id = Column(String(64), nullable=True)
    payload_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
