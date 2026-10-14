import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_vehicle_model_has_version_and_positive_constraint():
    source = (BACKEND / "models.py").read_text(encoding="utf-8")
    start = source.index("class Vehicle(Base):")
    end = source.index("class WorkSession(Base):", start)
    vehicle = source[start:end]
    assert "version            = Column(Integer, nullable=False, default=1, server_default='1')" in vehicle
    assert "CheckConstraint('version > 0', name='version_positive')" in vehicle


def _capability_members(name: str) -> list[str]:
    source = (BACKEND / "domains/authorization/capabilities.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        assert isinstance(node.value, ast.Call)
        assert isinstance(node.value.func, ast.Name) and node.value.func.id == "frozenset"
        assert len(node.value.args) == 1 and isinstance(node.value.args[0], ast.Set)
        return [
            element.value
            for element in node.value.args[0].elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
    raise AssertionError(f"{name} definition not found")


def test_vehicle_capabilities_are_company_only():
    permissions = _capability_members("PERMISSIONS")
    company_only = _capability_members("COMPANY_ONLY")

    assert permissions.count("vehicle.read") == 1
    assert permissions.count("vehicle.manage") == 1
    assert "vehicle.read" in company_only
    assert "vehicle.manage" in company_only

    for code in ("dispatch.read", "dispatch.execute", "location.read", "location.update", "location.state"):
        assert code in permissions
        assert code not in company_only


def test_vehicle_foundation_migration_extends_current_head_and_retains_permission_history():
    source = (BACKEND / "alembic/versions/c9e7a41d2b60_vehicle_v1_foundation.py").read_text(encoding="utf-8")
    assert 'down_revision = "b7a4c2d9e105"' in source
    assert 'sa.Column("version", sa.Integer(), nullable=False, server_default="1")' in source
    assert "('vehicle.read')" in source and "('vehicle.manage')" in source
    assert 'op.drop_column("vehicles", "version")' in source
    assert "DELETE FROM permissions" not in source
