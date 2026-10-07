from pathlib import Path

from models import InventoryTransferHeader
from sqlalchemy import CheckConstraint

ROOT = Path(__file__).resolve().parents[1]


def _distinct_location_constraint() -> CheckConstraint:
    matches = [
        constraint
        for constraint in InventoryTransferHeader.__table__.constraints
        if isinstance(constraint, CheckConstraint)
        and "distinct_locations" in str(constraint.name)
    ]
    assert len(matches) == 1
    return matches[0]


def test_transfer_header_allows_only_scoped_inplace_quality_evidence():
    sql = " ".join(str(_distinct_location_constraint().sqltext).split())
    assert "source_location_id <> destination_location_id" in sql
    assert "workflow_type = 'DIRECT'" in sql
    assert "status = 'POSTED'" in sql
    assert "transfer_purpose IN ('DISPOSAL','RETURN_TO_VENDOR')" in sql
    assert "reference_number LIKE 'QSTG-%'" in sql
    assert "tenant_policy_id IS NOT NULL" in sql
    assert "tenant_policy_revision IS NOT NULL" in sql
    assert "commercial_context ->> 'quality_stage_v1' = 'true'" in sql


def test_migration_preserves_regular_distinct_location_invariant_and_downgrade_evidence():
    migration = (
        ROOT / "alembic" / "versions" / "a4c9e7d2f631_allow_inplace_quality_stage.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision = "e31f6c2a9d74"' in migration
    assert "source_location_id <> destination_location_id" in migration
    assert "reference_number LIKE 'QSTG-%'" in migration
    assert "Cannot downgrade: in-place quality transfer evidence exists" in migration
    assert "fixed_name = op.f(_CONSTRAINT)" in migration
    assert "op.drop_constraint(fixed_name, _TABLE" in migration
    assert "op.create_check_constraint(fixed_name, _TABLE" in migration
