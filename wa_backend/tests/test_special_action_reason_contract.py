from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_batch_actions_expose_server_derived_unavailability_reasons():
    api = (ROOT / "api" / "warehouse" / "live_stock.py").read_text(encoding="utf-8")
    for reason in (
        "STATE_RESTRICTION",
        "NO_CONFIGURED_DESTINATION",
        "ALREADY_AT_DESTINATION",
        "SOURCE_CANNOT_SEND",
        "PERMISSION_REQUIRED",
        "NO_MOVABLE_QUANTITY",
        "ALLOWED",
    ):
        assert f'"{reason}"' in api
    assert 'special_actions.append({' in api
    assert 'item["purpose"] for item in special_actions if item["allowed"]' in api


def test_allowed_purposes_remains_compatibility_projection_of_action_options():
    api = (ROOT / "api" / "warehouse" / "live_stock.py").read_text(encoding="utf-8")
    assert '"special_actions": special_actions' in api
    assert '"allowed_purposes": list(allowed)' in api
