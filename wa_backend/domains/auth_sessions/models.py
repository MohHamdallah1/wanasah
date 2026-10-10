"""Additive principal-bound refresh persistence; no issuance or runtime cutover.

Like legacy RefreshToken, store the exact unique signed token value to retain
rotation's lost-response successor recovery. Successors remain in the same
company/principal/channel; deleting one clears only its predecessor's pointer.
"""
from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKeyConstraint,
    Index, Integer, String, UniqueConstraint, text,
)

from models import Base, utc_now
from domains.identity import models as identity_models  # noqa: F401


class PrincipalRefreshToken(Base):
    __tablename__ = "principal_refresh_tokens"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_principal_refresh_tokens_company_id"),
        UniqueConstraint("company_id", "principal_id", "channel", "id", name="uq_principal_refresh_tokens_session_id"),
        UniqueConstraint("token", name="uq_principal_refresh_tokens_token"),
        ForeignKeyConstraint(
            ["company_id", "principal_id"], ["company_principals.company_id", "company_principals.id"],
            name="fk_principal_refresh_tokens_tenant_principal", ondelete="CASCADE", onupdate="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "principal_id", "channel", "replaced_by_id"],
            ["principal_refresh_tokens.company_id", "principal_refresh_tokens.principal_id",
             "principal_refresh_tokens.channel", "principal_refresh_tokens.id"],
            name="fk_principal_refresh_tokens_session_successor",
            ondelete="SET NULL (replaced_by_id)", onupdate="RESTRICT",
        ),
        CheckConstraint("channel IN ('DASHBOARD', 'FIELD')", name="channel"),
        CheckConstraint("auth_revision > 0", name="auth_revision_positive"),
        Index("uq_principal_refresh_tokens_replaced_by_id", "replaced_by_id", unique=True),
        Index("ix_principal_refresh_tokens_principal_channel", "company_id", "principal_id", "channel", "is_revoked", "id"),
        Index("ix_principal_refresh_tokens_expires_at", "expires_at"),
        Index("ix_principal_refresh_tokens_tenant_revocation_expiry", "company_id", "is_revoked", "expires_at", "id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, nullable=False)
    principal_id = Column(Integer, nullable=False)
    channel = Column(String(16), nullable=False)
    token = Column(String(500), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    replaced_by_id = Column(Integer, nullable=True)
    # Explicit snapshot of the issuing principal's revision; no implicit revision.
    auth_revision = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
