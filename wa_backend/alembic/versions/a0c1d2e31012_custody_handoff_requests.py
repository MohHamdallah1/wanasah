"""CUSTODY-P0: durable server-owned vehicle requests, tenant RLS/FORCE, revocation history."""
import os
import re
from alembic import op
from sqlalchemy.engine import make_url
import sqlalchemy as sa

revision = "a0c1d2e31012"
down_revision = "e4b7c9d2a601"
branch_labels = None
depends_on = None

TABLE = "vehicle_custody_handoffs"


def _runtime_role():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("CUSTODY-P0 requires DATABASE_URL")
    role = make_url(url).username
    if not role or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", role):
        raise RuntimeError("Invalid runtime role")
    row = op.get_bind().execute(sa.text(
        "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=:n"
    ), {"n": role}).mappings().one_or_none()
    if row is None or row["rolsuper"] or row["rolbypassrls"]:
        raise RuntimeError("Custody runtime must be NOSUPERUSER/NOBYPASSRLS")
    return '"' + role + '"'


def upgrade():
    role = _runtime_role()
    op.execute("""CREATE TABLE vehicle_custody_handoffs (
        id BIGSERIAL PRIMARY KEY,
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
        vehicle_id INTEGER NOT NULL,
        vehicle_location_id INTEGER NOT NULL,
        manager_principal_id INTEGER NOT NULL,
        target_driver_id INTEGER NOT NULL,
        recipient_rep_id INTEGER NOT NULL,
        recipient_principal_id INTEGER NOT NULL,
        prior_epoch_id BIGINT,
        mode VARCHAR(16) NOT NULL,
        expected_context_revision BIGINT NOT NULL,
        expected_stock_snapshot VARCHAR(64) NOT NULL,
        request_id VARCHAR(36) NOT NULL,
        request_hash VARCHAR(64) NOT NULL,
        offer_issued_at BIGINT NOT NULL,
        expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        state VARCHAR(16) NOT NULL,
        decision_request_id VARCHAR(36),
        decision_hash VARCHAR(64),
        confirmed_at BIGINT,
        confirmed_auth_revision INTEGER,
        decline_reason_code VARCHAR(32),
        decline_reason_text VARCHAR(300),
        cancel_request_id VARCHAR(36),
        approve_request_id VARCHAR(36),
        accepted_epoch_id BIGINT,
        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_custody_handoff_tenant_id UNIQUE (company_id,id),
        CONSTRAINT uq_custody_handoff_create_uuid UNIQUE (company_id,request_id),
        CONSTRAINT uq_custody_handoff_decision_uuid UNIQUE (company_id,decision_request_id),
        CONSTRAINT uq_custody_handoff_cancel_uuid UNIQUE (company_id,cancel_request_id),
        CONSTRAINT uq_custody_handoff_approve_uuid UNIQUE (company_id,approve_request_id),
        CONSTRAINT fk_custody_handoff_vehicle FOREIGN KEY (company_id,vehicle_id)
          REFERENCES vehicles(company_id,id) ON DELETE RESTRICT,
        CONSTRAINT fk_custody_handoff_vehicle_location FOREIGN KEY (company_id,vehicle_location_id,vehicle_id)
          REFERENCES inventory_locations(company_id,id,vehicle_id) ON DELETE RESTRICT,
        CONSTRAINT fk_custody_handoff_manager FOREIGN KEY (company_id,manager_principal_id)
          REFERENCES company_principals(company_id,id) ON DELETE RESTRICT,
        CONSTRAINT fk_custody_handoff_recipient FOREIGN KEY (company_id,recipient_principal_id)
          REFERENCES company_principals(company_id,id) ON DELETE RESTRICT,
        CONSTRAINT fk_custody_handoff_rep FOREIGN KEY (company_id,recipient_rep_id,recipient_principal_id)
          REFERENCES field_representatives(company_id,id,principal_id) ON DELETE RESTRICT,
        CONSTRAINT fk_custody_handoff_prior_epoch FOREIGN KEY (company_id,prior_epoch_id)
          REFERENCES vehicle_custody_epochs(company_id,id) ON DELETE RESTRICT,
        CONSTRAINT fk_custody_handoff_accepted_epoch FOREIGN KEY (company_id,accepted_epoch_id)
          REFERENCES vehicle_custody_epochs(company_id,id) ON DELETE RESTRICT,
        CONSTRAINT custody_handoff_state_valid CHECK (state IN
          ('PENDING','CONFIRMED','DECLINED','CANCELLED','EXPIRED','COMMITTED')),
        CONSTRAINT custody_handoff_mode_valid CHECK (mode IN ('FIRST_ACCEPT','REASSIGN')),
        CONSTRAINT custody_handoff_revision_valid CHECK (expected_context_revision >= 0 AND offer_issued_at > 0),
        CONSTRAINT custody_handoff_confirmation_valid CHECK
          ((confirmed_at IS NULL AND confirmed_auth_revision IS NULL OR
            confirmed_at IS NOT NULL AND confirmed_auth_revision IS NOT NULL) AND
            (state NOT IN ('CONFIRMED','COMMITTED') OR confirmed_at IS NOT NULL)),
        CONSTRAINT custody_handoff_commit_valid CHECK
          ((state = 'COMMITTED') = (accepted_epoch_id IS NOT NULL AND approve_request_id IS NOT NULL))
    )""")
    op.execute("CREATE UNIQUE INDEX uq_custody_handoff_live_vehicle ON vehicle_custody_handoffs(company_id,vehicle_id) WHERE state IN ('PENDING','CONFIRMED')")
    op.execute("CREATE INDEX ix_custody_handoff_latest_vehicle ON vehicle_custody_handoffs(company_id,vehicle_id,id)")
    op.execute("CREATE INDEX ix_custody_handoff_recipient ON vehicle_custody_handoffs(company_id,recipient_principal_id,state,expires_at,id)")
    guard = "company_id = NULLIF(current_setting('app.current_tenant',true),'')::integer"
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY custody_handoff_tenant_access ON {TABLE} USING ({guard}) WITH CHECK ({guard})")
    op.execute(f"CREATE POLICY custody_handoff_tenant_guard ON {TABLE} AS RESTRICTIVE USING ({guard}) WITH CHECK ({guard})")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLE} TO {role}")
    op.execute(f"REVOKE TRUNCATE, REFERENCES, TRIGGER ON {TABLE} FROM {role}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {TABLE}_id_seq TO {role}")
    op.execute(f"REVOKE UPDATE ON SEQUENCE {TABLE}_id_seq FROM {role}")


def downgrade():
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM vehicle_custody_handoffs")).scalar()
    if count:
        raise RuntimeError("Cannot downgrade durable custody requests: revoke/history would be lost")
    op.drop_table(TABLE)
