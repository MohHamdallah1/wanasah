from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_vehicle_model_has_version_and_positive_constraint():
    source = (BACKEND / "models.py").read_text(encoding="utf-8")
    start = source.index("class Vehicle(Base):")
    end = source.index("class WorkSession(Base):", start)
    vehicle = source[start:end]
    assert "version            = Column(Integer, nullable=False, default=1, server_default='1')" in vehicle
    assert "CheckConstraint('version > 0', name='ck_vehicles_version_positive')" in vehicle


def test_vehicle_capabilities_are_company_only():
    source = (BACKEND / "domains/authorization/capabilities.py").read_text(encoding="utf-8")
    assert source.count("'vehicle.read'") == 2
    assert source.count("'vehicle.manage'") == 2


def test_vehicle_foundation_migration_extends_current_head_and_retains_permission_history():
    source = (BACKEND / "alembic/versions/c9e7a41d2b60_vehicle_v1_foundation.py").read_text(encoding="utf-8")
    assert 'down_revision = "b7a4c2d9e105"' in source
    assert 'sa.Column("version", sa.Integer(), nullable=False, server_default="1")' in source
    assert "('vehicle.read')" in source and "('vehicle.manage')" in source
    assert 'op.drop_column("vehicles", "version")' in source
    assert "DELETE FROM permissions" not in source
