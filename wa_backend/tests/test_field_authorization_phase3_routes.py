"""Inspect the actual application registry, including custom batch registration."""
import inspect
from collections import Counter
from pathlib import Path
from fastapi.routing import APIRoute
from main import app
from api import driver, field_contracts, reconciliation

MANIFEST=[
    [
        "POST",
        "/driver/sessions/start",
        "start_work_session"
    ],
    [
        "PUT",
        "/driver/sessions/end",
        "end_work_session"
    ],
    [
        "PUT",
        "/driver/sessions/break",
        "toggle_break"
    ],
    [
        "PUT",
        "/visits/{visit_id}",
        "update_visit"
    ],
    [
        "GET",
        "/driver/dashboard",
        "get_driver_dashboard"
    ],
    [
        "PUT",
        "/driver/transfers/{transfer_id}/respond",
        "respond_to_transfer"
    ],
    [
        "PUT",
        "/driver/transfers/batch_respond",
        "batch_respond_to_transfers"
    ],
    [
        "GET",
        "/driver/transfers/pending",
        "get_pending_transfers"
    ],
    [
        "POST",
        "/shops",
        "add_new_shop"
    ],
    [
        "GET",
        "/product_variants",
        "get_products"
    ],
    [
        "GET",
        "/driver/visits",
        "get_driver_visits"
    ],
    [
        "GET",
        "/visits/{visit_id}",
        "get_visit_details"
    ],
    [
        "GET",
        "/driver/sessions/active",
        "get_active_session"
    ],
    [
        "POST",
        "/visits/{visit_id}/return-resolution",
        "resolve_visit_return"
    ],
    [
        "GET",
        "/visits/{visit_id}/commercial-state",
        "get_visit_commercial_state"
    ],
    [
        "POST",
        "/visits/{visit_id}/invoice-preview",
        "preview_visit_invoice"
    ],
    [
        "GET",
        "/visits/{visit_id}/invoice",
        "get_visit_invoice"
    ],
    [
        "GET",
        "/driver/custody",
        "get_field_custody"
    ],
    [
        "POST",
        "/driver/session/{session_id}/reconcile",
        "reconcile_driver_end_of_day"
    ]
]


def dependencies(node):
    yield node.call
    for child in node.dependencies:
        yield from dependencies(child)


def test_complete_d7_registry_without_duplicate_or_alias_bypass():
    expected={(m,p,n) for m,p,n in MANIFEST}
    modules={driver.__name__,field_contracts.__name__,reconciliation.__name__}
    actual={(m,r.path,r.endpoint.__name__) for r in app.routes if isinstance(r,APIRoute)
            and r.endpoint.__module__ in modules for m in r.methods}
    assert actual==expected
    counts=Counter((m,r.path) for r in app.routes if isinstance(r,APIRoute) for m in r.methods)
    assert all(counts[(m,p)]==1 for m,p,_n in MANIFEST)
    guarded=set()
    for route in app.routes:
        if not isinstance(route,APIRoute):
            continue
        names={getattr(c,"__name__","") for c in dependencies(route.dependant)}
        if "get_current_field_context" in names:
            guarded.update((m,route.path,route.endpoint.__name__) for m in route.methods)
            assert "get_current_field_capability_access" in names
    assert guarded==expected-{("GET","/visits/{visit_id}","get_visit_details")}
    source=inspect.getsource(driver.get_visit_details)
    field=source.split("if isinstance(current, FieldRequestContext):",1)[1].split("elif",1)[0]
    assert 'require_field_capability("visit.read")(access=access)' in field
    assert field.index('require_field_capability') < field.index('get_current_field_legacy_driver')
    assert 'await access.require("visit.read")' in source  # Shared Backoffice guard preserved.


def test_authentication_boundaries_have_no_business_capability_dependency():
    found=set()
    for route in app.routes:
        if isinstance(route,APIRoute) and route.path in ("/driver/login","/refresh","/logout"):
            names={getattr(c,"__name__","") for c in dependencies(route.dependant)}
            assert "get_current_field_capability_access" not in names
            found.add(route.path)
    assert found=={"/driver/login","/refresh","/logout"}


def test_every_narrow_production_edit_is_only_authorization_integration():
    import ast
    root=Path(__file__).resolve().parents[1]
    for module in ("api/driver.py","api/field_contracts.py","api/reconciliation.py",
                   "api/authentication/field_transfer_authorization.py"):
        ast.parse((root/module).read_text(encoding="utf-8"))
    transfer=(root/"api/authentication/field_transfer_authorization.py").read_text()
    assert "for item in payload.transfers" in transfer
    assert "transfer.receive" in transfer and "transfer.reject" in transfer
    assert "batch_id" not in transfer
    assert not any(x in transfer for x in (".commit(", ".add(", "begin_idempotent_operation"))
