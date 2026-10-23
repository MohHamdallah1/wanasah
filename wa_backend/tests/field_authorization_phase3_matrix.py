"""Frozen D7 cases: concrete registered URLs and payloads, never mocks."""
from uuid import uuid4

CASES = [
    {
        "method": "POST",
        "path": "/driver/sessions/start",
        "codes": [
            "work_session.execute"
        ],
        "name": "start_work_session"
    },
    {
        "method": "PUT",
        "path": "/driver/sessions/end",
        "codes": [
            "work_session.execute"
        ],
        "name": "end_work_session"
    },
    {
        "method": "PUT",
        "path": "/driver/sessions/break",
        "codes": [
            "work_session.execute"
        ],
        "name": "toggle_break"
    },
    {
        "method": "PUT",
        "path": "/visits/{visit_id}",
        "codes": [
            "visit.execute"
        ],
        "name": "update_visit"
    },
    {
        "method": "GET",
        "path": "/driver/dashboard",
        "codes": [
            "work_session.read",
            "visit.read",
            "inventory.read"
        ],
        "name": "get_driver_dashboard"
    },
    {
        "method": "GET",
        "path": "/driver/transfers/pending",
        "codes": [
            "transfer.read"
        ],
        "name": "get_pending_transfers"
    },
    {
        "method": "POST",
        "path": "/shops",
        "codes": [
            "shop.create"
        ],
        "name": "add_new_shop"
    },
    {
        "method": "GET",
        "path": "/product_variants",
        "codes": [
            "catalog.read",
            "pricing.view"
        ],
        "name": "get_products"
    },
    {
        "method": "GET",
        "path": "/driver/visits",
        "codes": [
            "visit.read",
            "inventory.read",
            "transfer.read",
            "pricing.view"
        ],
        "name": "get_driver_visits"
    },
    {
        "method": "GET",
        "path": "/visits/{visit_id}",
        "codes": [
            "visit.read"
        ],
        "name": "get_visit_details"
    },
    {
        "method": "GET",
        "path": "/driver/sessions/active",
        "codes": [
            "work_session.read"
        ],
        "name": "get_active_session"
    },
    {
        "method": "POST",
        "path": "/visits/{visit_id}/return-resolution",
        "codes": [
            "visit.execute"
        ],
        "name": "resolve_visit_return"
    },
    {
        "method": "GET",
        "path": "/visits/{visit_id}/commercial-state",
        "codes": [
            "visit.read"
        ],
        "name": "get_visit_commercial_state"
    },
    {
        "method": "POST",
        "path": "/visits/{visit_id}/invoice-preview",
        "codes": [
            "visit.execute",
            "pricing.view"
        ],
        "name": "preview_visit_invoice"
    },
    {
        "method": "GET",
        "path": "/visits/{visit_id}/invoice",
        "codes": [
            "visit.read",
            "pricing.view"
        ],
        "name": "get_visit_invoice"
    },
    {
        "method": "GET",
        "path": "/driver/custody",
        "codes": [
            "inventory.read"
        ],
        "name": "get_field_custody"
    },
    {
        "method": "POST",
        "path": "/driver/session/{session_id}/reconcile",
        "codes": [
            "reconciliation.execute"
        ],
        "name": "reconcile_driver_end_of_day"
    },
    {
        "method": "PUT",
        "path": "/driver/transfers/{transfer_id}/respond",
        "codes": [
            "transfer.receive"
        ],
        "name": "accept"
    },
    {
        "method": "PUT",
        "path": "/driver/transfers/{transfer_id}/respond",
        "codes": [
            "transfer.reject"
        ],
        "name": "reject"
    },
    {
        "method": "PUT",
        "path": "/driver/transfers/batch_respond",
        "codes": [
            "transfer.receive"
        ],
        "name": "batch_accepted"
    },
    {
        "method": "PUT",
        "path": "/driver/transfers/batch_respond",
        "codes": [
            "transfer.reject"
        ],
        "name": "batch_rejected"
    },
    {
        "method": "PUT",
        "path": "/driver/transfers/batch_respond",
        "codes": [
            "transfer.receive",
            "transfer.reject"
        ],
        "name": "batch_mixed"
    }
]


def request_case(g, case):
    path=case["path"].format(visit_id=g.visit,session_id=g.session,transfer_id=g.transfers[0])
    name=case["name"]
    body=None
    if name=="start_work_session":
        body={}
    elif name=="toggle_break":
        body={"action":"start"}
    elif name=="update_visit":
        body={"request_id":str(uuid4()),"outcome":"NoSale","notes":"Synthetic no sale"}
    elif name=="add_new_shop":
        body={"request_id":str(uuid4()),"name":"Synthetic shop","phone_number":uuid4().hex[:15],
              "latitude":31.9,"longitude":35.9}
    elif name=="resolve_visit_return":
        body={"product_variant_id":g.variant["id"],"packs_quantity":1,"return_type":"Damaged"}
    elif name=="preview_visit_invoice":
        body={"cart_items":[{"product_variant_id":g.variant["id"],"packs_quantity":1}]}
    elif name=="reconcile_driver_end_of_day":
        body={"counts":[{"product_variant_id":g.variant["id"],"actual_quantity":"150"}]}
    elif name in ("accept","reject"):
        body={"response":"accepted" if name=="accept" else "rejected","reason":"Synthetic reason"}
    elif name.startswith("batch_"):
        decisions=["accepted","rejected"] if name=="batch_mixed" else [name.removeprefix("batch_")]*2
        body={"transfers":[{"transfer_id":i,"status":d,"reason":"Synthetic reason"}
                            for i,d in zip(g.transfers,decisions)]}
    return case["method"],path,body
