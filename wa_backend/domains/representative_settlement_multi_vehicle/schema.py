"""Ordered M04 DDL implementation, awaiting merged M02/M03 revision binding.

This is not an Alembic revision and does not change the repository graph.
The final single ordered revision calls this through Alembic Operations.
"""
import re

from sqlalchemy import text
from sqlalchemy.schema import CreateIndex, CreateTable

from .models import VehicleCustodyCheckpoint, VehicleCustodyCheckpointEpoch, VehicleCustodyCheckpointLine

TABLES = (VehicleCustodyCheckpoint.__table__, VehicleCustodyCheckpointEpoch.__table__,
          VehicleCustodyCheckpointLine.__table__)


def upgrade_checkpoint_schema(op, *, runtime_role):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", runtime_role):
        raise RuntimeError("Unsafe runtime role")
    bind = op.get_bind()
    role = bind.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=:r"),
                        {"r": runtime_role}).one_or_none()
    if role is None or any(role):
        raise RuntimeError("M04 requires a restricted NOBYPASSRLS runtime role")
    scoped = bind.execute(text("""SELECT EXISTS (
        SELECT 1 FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid
        AND a.attnum=ANY(i.indkey)
        WHERE i.indrelid='session_inventory_snapshots'::regclass AND i.indisunique
        AND a.attname='location_id')""")).scalar_one()
    if not scoped:
        raise RuntimeError("M04 requires merged M03 location-scoped snapshot schema")
    # The corresponding minimal models.py parity hunk remains LEAD-owned until
    # explicitly approved after M03 merge. Do not modify ORM from this builder.
    op.drop_index("uq_vehicle_recon_work_session", table_name="stocktake_sessions")
    op.create_index("uq_vehicle_recon_work_session", "stocktake_sessions",
                    ["company_id", "related_work_session_id", "location_id"], unique=True,
                    postgresql_where=text("stocktake_type = 'VEHICLE_RECON' "
                                          "AND related_work_session_id IS NOT NULL AND status <> 'CANCELLED'"))
    for table in TABLES:
        op.execute(CreateTable(table))
        for index in sorted(table.indexes, key=lambda i: i.name):
            op.execute(CreateIndex(index))
        tenant = "company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer"
        name = table.name
        op.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY m04_tenant_access ON "{name}" USING ({tenant}) WITH CHECK ({tenant})')
        op.execute(f'CREATE POLICY m04_tenant_guard ON "{name}" AS RESTRICTIVE '
                   f'USING ({tenant}) WITH CHECK ({tenant})')
        op.execute(f'GRANT SELECT, INSERT ON "{name}" TO "{runtime_role}"')
        op.execute(f'REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON "{name}" FROM "{runtime_role}"')
    op.execute(f'GRANT USAGE, SELECT ON SEQUENCE representative_vehicle_custody_checkpoints_id_seq '
               f'TO "{runtime_role}"')
    op.execute("""CREATE FUNCTION m04_custody_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'M04 signed custody evidence is immutable' USING ERRCODE='23514'; END $$""")
    for table in TABLES:
        op.execute(f'CREATE TRIGGER m04_immutable BEFORE UPDATE OR DELETE ON "{table.name}" '
                   'FOR EACH ROW EXECUTE FUNCTION m04_custody_immutable()')
    op.execute("""CREATE FUNCTION m04_custody_scope() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_TABLE_NAME = 'representative_vehicle_custody_checkpoints' THEN
          IF NOT EXISTS (
            SELECT 1 FROM vehicle_custody_epochs e JOIN work_sessions w
              ON w.company_id=e.company_id AND w.id=NEW.work_session_id
            JOIN company_principals p ON p.company_id=e.company_id AND p.id=NEW.signed_by_principal_id
            WHERE e.company_id=NEW.company_id AND e.id=NEW.latest_epoch_id
              AND e.vehicle_id=NEW.vehicle_id AND e.vehicle_location_id=NEW.vehicle_location_id
              AND e.context_revision=NEW.latest_epoch_revision AND e.state='ACCEPTED'
              AND (e.related_session_id IS NULL OR e.related_session_id=NEW.work_session_id)
              AND w.end_time IS NOT NULL AND w.is_settled IS FALSE AND NEW.signed_at>=w.end_time
              AND p.principal_type='BACKOFFICE') THEN
            RAISE EXCEPTION 'M04 custody scope mismatch' USING ERRCODE='23514';
          END IF;
          IF NEW.mode='PHYSICAL_HANDOFF' AND NOT EXISTS (
            SELECT 1 FROM inventory_locations l WHERE l.company_id=NEW.company_id
              AND l.id=NEW.destination_location_id AND l.location_type='WAREHOUSE' AND l.is_active) THEN
            RAISE EXCEPTION 'M04 physical destination mismatch' USING ERRCODE='23514';
          END IF;
        ELSE
          IF NOT EXISTS (
            SELECT 1 FROM representative_vehicle_custody_checkpoints c JOIN vehicle_custody_epochs e
              ON e.company_id=c.company_id AND e.vehicle_id=c.vehicle_id
              AND e.vehicle_location_id=c.vehicle_location_id
            WHERE c.company_id=NEW.company_id AND c.id=NEW.checkpoint_id
              AND c.work_session_id=NEW.work_session_id AND e.id=NEW.epoch_id
              AND (e.related_session_id IS NULL OR e.related_session_id=NEW.work_session_id)
              AND e.state='ACCEPTED') THEN
            RAISE EXCEPTION 'M04 epoch scope mismatch' USING ERRCODE='23514';
          END IF;
        END IF;
        RETURN NEW;
      END $$""")
    for table in TABLES[:2]:
        op.execute(f'CREATE TRIGGER m04_scope BEFORE INSERT ON "{table.name}" '
                   'FOR EACH ROW EXECUTE FUNCTION m04_custody_scope()')
    # Installed LAST. Runtime writers remain closed without this complete
    # migration-owned contract and both location-scoped unique prerequisites.
    op.execute("CREATE FUNCTION m04_custody_contract_version() RETURNS integer "
               "LANGUAGE sql IMMUTABLE AS 'SELECT 1'")
    op.execute(f'GRANT EXECUTE ON FUNCTION m04_custody_contract_version() TO "{runtime_role}"')


def downgrade_checkpoint_schema(op):
    for table in TABLES:
        exists = op.get_bind().execute(text(f'SELECT EXISTS(SELECT 1 FROM "{table.name}" LIMIT 1)')).scalar_one()
        if exists:
            raise RuntimeError("M04 downgrade would destroy signed custody history")
    op.execute("DROP FUNCTION m04_custody_contract_version()")
    for table in reversed(TABLES):
        op.drop_table(table.name)
    op.execute("DROP FUNCTION m04_custody_scope()")
    op.execute("DROP FUNCTION m04_custody_immutable()")
    # Only safe before any canonical multi-vehicle variance was recorded.
    ambiguous = op.get_bind().execute(text("""SELECT EXISTS (
        SELECT 1 FROM stocktake_sessions WHERE stocktake_type='VEHICLE_RECON' AND status<>'CANCELLED'
        GROUP BY company_id,related_work_session_id HAVING COUNT(*)>1)""")).scalar_one()
    if ambiguous:
        raise RuntimeError("M04 downgrade would remove multi-vehicle variance protection")
    op.drop_index("uq_vehicle_recon_work_session", table_name="stocktake_sessions")
    op.create_index("uq_vehicle_recon_work_session", "stocktake_sessions",
                    ["company_id", "related_work_session_id"], unique=True,
                    postgresql_where=text("stocktake_type = 'VEHICLE_RECON' "
                                          "AND related_work_session_id IS NOT NULL AND status <> 'CANCELLED'"))
