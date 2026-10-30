"""Independently predetermined Decimal truth for the V1 A->B/count journey."""
from dataclasses import asdict, dataclass
from decimal import Decimal

D = Decimal


@dataclass(frozen=True)
class Expected:
    stage: str
    a_first: Decimal
    a_second: Decimal
    b_first: Decimal
    transit_first: Decimal
    reserved_a: Decimal
    movements: int
    cost_events: int
    cost_quantity: Decimal
    inventory_value: Decimal
    average_cost: Decimal
    attempts: int = 0
    locks: int = 0
    stocktake_status: str | None = None


def matrix(method):
    # Receipt 1: 100 cartons * 8 * 2/base = 1600.
    # Receipt 2: 50 cartons * 8 * 5/base = 2000.
    # Transfer: 15 cartons * 8 = 120, physically FIRST lot, financially neutral.
    # Rejected transfer: 2 cartons * 8 = 16, returned to source.
    # Count B: expected120, actual104; loss16.
    # FIFO consumes16*2=32; moving-average consumes16*3=48.
    rows = [
        Expected("inbound_first", D("800"), D("0"), D("0"), D("0"), D("0"), 1, 1, D("800"), D("1600"), D("2")),
        Expected("inbound_second", D("800"), D("400"), D("0"), D("0"), D("0"), 2, 2, D("1200"), D("3600"), D("3")),
        Expected("reserved", D("800"), D("400"), D("0"), D("0"), D("16"), 3, 2, D("1200"), D("3600"), D("3")),
        Expected("dispatched_15_cartons", D("680"), D("400"), D("0"), D("120"), D("16"), 4, 2, D("1200"), D("3600"), D("3")),
        Expected("received", D("680"), D("400"), D("120"), D("0"), D("16"), 5, 2, D("1200"), D("3600"), D("3")),
        Expected("reject_dispatched", D("664"), D("400"), D("120"), D("16"), D("16"), 6, 2, D("1200"), D("3600"), D("3")),
        Expected("rejected_to_source", D("680"), D("400"), D("120"), D("0"), D("16"), 7, 2, D("1200"), D("3600"), D("3")),
        Expected("released", D("680"), D("400"), D("120"), D("0"), D("0"), 8, 2, D("1200"), D("3600"), D("3")),
        Expected("count_started", D("680"), D("400"), D("120"), D("0"), D("0"), 8, 2, D("1200"), D("3600"), D("3"), 0, 1, "COUNTING"),
        Expected("first_count_review", D("680"), D("400"), D("120"), D("0"), D("0"), 8, 2, D("1200"), D("3600"), D("3"), 1, 1, "PENDING_REVIEW"),
        Expected("recount_authorized", D("680"), D("400"), D("120"), D("0"), D("0"), 8, 2, D("1200"), D("3600"), D("3"), 1, 1, "RECOUNT_REQUIRED"),
        Expected("independent_count_review", D("680"), D("400"), D("120"), D("0"), D("0"), 8, 2, D("1200"), D("3600"), D("3"), 2, 1, "PENDING_REVIEW"),
        Expected("stocktake_posted", D("680"), D("400"), D("104"), D("0"), D("0"), 9, 3, D("1184"),
                 D("3568") if method == "FIFO" else D("3552"),
                 D("3.013514") if method == "FIFO" else D("3"), 2, 0, "POSTED"),
    ]
    return {row.stage: row for row in rows}


def expected_manifest(method):
    return [asdict(row) for row in matrix(method).values()]
