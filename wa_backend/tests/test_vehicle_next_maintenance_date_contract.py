from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4


BACKEND = Path(__file__).resolve().parents[1]


def _load_schemas_module():
    path = BACKEND / "api/vehicles/schemas.py"
    spec = spec_from_file_location("vehicle_schemas_contract_test", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_create_accepts_optional_and_past_next_maintenance_date_without_status_mutation():
    schemas = _load_schemas_module()
    omitted = schemas.VehicleCreateRequest(
        request_id=uuid4(), plate_number="12-34567", current_mileage=0
    )
    assert omitted.next_maintenance_date is None
    assert "next_maintenance_date" not in omitted.model_fields_set
    assert omitted.maintenance_status == "Active"

    overdue = schemas.VehicleCreateRequest(
        request_id=uuid4(),
        plate_number="12-34568",
        current_mileage=1,
        next_maintenance_date=date(2020, 1, 2),
    )
    assert overdue.next_maintenance_date == date(2020, 1, 2)
    assert overdue.maintenance_status == "Active"


def test_update_distinguishes_omission_set_and_explicit_null_clear():
    schemas = _load_schemas_module()
    request_id = uuid4()
    omitted = schemas.VehicleUpdateRequest(
        request_id=request_id, expected_version=1, vehicle_type="Van"
    )
    omitted_fields = omitted.model_dump(
        exclude={"request_id", "expected_version"}, exclude_unset=True
    )
    assert "next_maintenance_date" not in omitted_fields

    scheduled = schemas.VehicleUpdateRequest(
        request_id=request_id,
        expected_version=1,
        next_maintenance_date=date(2021, 3, 4),
    )
    scheduled_fields = scheduled.model_dump(
        exclude={"request_id", "expected_version"}, exclude_unset=True
    )
    assert scheduled_fields == {"next_maintenance_date": date(2021, 3, 4)}

    cleared = schemas.VehicleUpdateRequest(
        request_id=request_id, expected_version=1, next_maintenance_date=None
    )
    cleared_fields = cleared.model_dump(
        exclude={"request_id", "expected_version"}, exclude_unset=True
    )
    assert cleared_fields == {"next_maintenance_date": None}


def test_response_and_list_contract_carry_next_maintenance_date():
    schemas = _load_schemas_module()
    payload = {
        "id": 7,
        "plate_number": "12-34567",
        "vehicle_type": None,
        "current_mileage": 100,
        "next_oil_change": None,
        "license_expiry_date": None,
        "next_maintenance_date": "2026-12-15",
        "maintenance_status": "Active",
        "is_active": True,
        "version": 3,
        "custody_ready": True,
    }
    response = schemas.VehicleResponse.model_validate(payload)
    page = schemas.VehicleCursorPage(items=[response], next_cursor=None, has_more=False)
    assert page.items[0].next_maintenance_date == date(2026, 12, 15)
    assert page.items[0].maintenance_status == "Active"


def test_domain_and_api_wiring_preserve_set_clear_without_automatic_status_change():
    validation = (BACKEND / "domains/vehicles/validation.py").read_text(encoding="utf-8")
    contracts = (BACKEND / "domains/vehicles/contracts.py").read_text(encoding="utf-8")
    management = (BACKEND / "domains/vehicles/management.py").read_text(encoding="utf-8")
    queries = (BACKEND / "domains/vehicles/queries.py").read_text(encoding="utf-8")
    api = (BACKEND / "api/vehicles/management.py").read_text(encoding="utf-8")

    assert '"next_maintenance_date"' in validation
    assert '("license_expiry_date", "next_maintenance_date")' in validation
    assert "next_maintenance_date: date | None = None" in contracts
    assert '"next_maintenance_date": command.next_maintenance_date' in management
    assert "next_maintenance_date=command.next_maintenance_date" in management
    assert "next_maintenance_date=payload.next_maintenance_date" in api
    assert '"next_maintenance_date": (' in queries
    assert "date.today" not in validation
    assert "next_maintenance_date" not in management[
        management.index('fields.get("maintenance_status")'):management.index("changed = False")
    ]


def test_model_and_migration_are_nullable_business_date_and_non_destructive():
    model = (BACKEND / "models.py").read_text(encoding="utf-8")
    migration = (BACKEND / "alembic/versions/d1a8f6c3b742_vehicle_next_maintenance_date.py").read_text(encoding="utf-8")

    assert "next_maintenance_date = Column(Date,     nullable=True)" in model
    assert 'down_revision = "c9e7a41d2b60"' in migration
    assert 'sa.Column("next_maintenance_date", sa.Date(), nullable=True)' in migration
    assert "UPDATE VEHICLES" not in migration.upper()
