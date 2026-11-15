"""#773: single-source posted Batch current metadata with append-only audit; no financial changes."""
import os
import re
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url

revision = "b77c4e2a1073"
down_revision = "a0c1d2e31012"
branch_labels = None
depends_on = None
TABLE="batch_metadata_correction_events"


def _runtime_role():
    value=os.getenv("DATABASE_URL")
    if not value: raise RuntimeError("BATCH-773 requires explicit DATABASE_URL")
    role=make_url(value).username
    if not role or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_$]*",role):
        raise RuntimeError("Invalid runtime role")
    row=op.get_bind().execute(sa.text(
        "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=:role"
    ),{"role":role}).mappings().one_or_none()
    if row is None or row["rolsuper"] or row["rolbypassrls"]:
        raise RuntimeError("BATCH-773 runtime role must be NOSUPERUSER/NOBYPASSRLS")
    return f'"{role}"'


def upgrade():
    role=_runtime_role()
    op.add_column("product_batches", sa.Column(
        "metadata_revision",sa.Integer(),nullable=False,server_default="1",
    ))
    op.create_check_constraint(
        "chk_product_batches_metadata_revision","product_batches","metadata_revision > 0",
    )
    op.create_table(
        TABLE,
        sa.Column("id",sa.BigInteger(),primary_key=True,autoincrement=True),
        sa.Column("company_id",sa.Integer(),nullable=False),
        sa.Column("batch_id",sa.Integer(),nullable=False),
        sa.Column("location_id",sa.Integer(),nullable=False),
        sa.Column("source_movement_id",sa.Integer(),nullable=False),
        sa.Column("source_cost_event_id",sa.BigInteger(),nullable=False),
        sa.Column("source_invoice",sa.String(length=100),nullable=False),
        sa.Column("revision",sa.Integer(),nullable=False),
        sa.Column("request_id",sa.String(length=36),nullable=False),
        sa.Column("actor_principal_id",sa.Integer(),nullable=False),
        sa.Column("actor_username",sa.String(length=80),nullable=False),
        sa.Column("actor_auth_revision",sa.Integer(),nullable=False),
        sa.Column("verified_at",sa.DateTime(),nullable=False),
        sa.Column("reason",sa.Text(),nullable=False),
        sa.Column("before_values",JSONB(),nullable=False),
        sa.Column("after_values",JSONB(),nullable=False),
        sa.Column("created_at",sa.DateTime(),nullable=False,server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("company_id","id",name="uq_batch_meta_event_tenant_id"),
        sa.UniqueConstraint("company_id","request_id",name="uq_batch_meta_event_request"),
        sa.UniqueConstraint("company_id","batch_id","revision",name="uq_batch_meta_event_revision"),
        sa.ForeignKeyConstraint(["company_id","batch_id"],["product_batches.company_id","product_batches.id"],ondelete="RESTRICT",name="fk_batch_meta_event_batch"),
        sa.ForeignKeyConstraint(["company_id","location_id"],["inventory_locations.company_id","inventory_locations.id"],ondelete="RESTRICT",name="fk_batch_meta_event_location"),
        sa.ForeignKeyConstraint(["company_id","source_movement_id"],["inventory_movements.company_id","inventory_movements.id"],ondelete="RESTRICT",name="fk_batch_meta_event_source_movement"),
        sa.ForeignKeyConstraint(["company_id","source_cost_event_id"],["inventory_cost_events.company_id","inventory_cost_events.id"],ondelete="RESTRICT",name="fk_batch_meta_event_source_cost"),
        sa.ForeignKeyConstraint(["company_id","actor_principal_id"],["company_principals.company_id","company_principals.id"],ondelete="RESTRICT",name="fk_batch_meta_event_principal"),
        sa.CheckConstraint("revision > 1 AND actor_auth_revision > 0",name="chk_batch_meta_event_revisions"),
        sa.CheckConstraint("length(trim(reason)) >= 8 AND length(reason) <= 500",name="chk_batch_meta_event_reason"),
        sa.CheckConstraint("length(trim(source_invoice)) > 0",name="chk_batch_meta_event_invoice"),
        sa.CheckConstraint("before_values <> after_values",name="chk_batch_meta_event_changed"),
    )
    op.create_index("ix_batch_meta_event_history",TABLE,["company_id","batch_id","id"])
    tenant="company_id = NULLIF(current_setting('app.current_tenant',true),'')::integer"
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY batch_meta_tenant ON {TABLE} USING ({tenant}) WITH CHECK ({tenant})")
    op.execute(f"CREATE POLICY batch_meta_tenant_restrict ON {TABLE} AS RESTRICTIVE USING ({tenant}) WITH CHECK ({tenant})")
    # Historical proof is permanently append-only for runtime. Even a
    # privileged accident must not be able to silently rewrite a signed event.
    op.execute("""CREATE FUNCTION block_batch_metadata_event_mutation()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Batch metadata correction history is append-only'; END;
    $$""")
    op.execute(f"""CREATE TRIGGER batch_meta_append_only
      BEFORE UPDATE OR DELETE ON {TABLE}
      FOR EACH ROW EXECUTE FUNCTION block_batch_metadata_event_mutation()""")
    op.execute(f"GRANT SELECT, INSERT ON {TABLE} TO {role}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON {TABLE} FROM {role}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {TABLE}_id_seq TO {role}")
    op.execute(f"REVOKE UPDATE ON SEQUENCE {TABLE}_id_seq FROM {role}")


def downgrade():
    if op.get_bind().execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar():
        raise RuntimeError("Cannot discard permanent batch correction audit history")
    op.drop_table(TABLE)
    op.execute("DROP FUNCTION block_batch_metadata_event_mutation()")
    op.drop_constraint("chk_product_batches_metadata_revision","product_batches",type_="check")
    op.drop_column("product_batches","metadata_revision")
