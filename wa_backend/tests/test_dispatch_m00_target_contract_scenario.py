"""M00 target *design* scenario: deliberately no imports from production APIs/ORM.

This isolated in-memory contract model is not PG16, HTTP, FIELD, Flutter, or
actual M01 implementation verification. It fixes invariants before migrations.
"""
from dataclasses import dataclass, field

from contextlib import contextmanager


@contextmanager
def expect_value_error(fragment: str):
    try:
        yield
    except ValueError as error:
        assert fragment in str(error), (fragment, error)
    else:
        raise AssertionError(f"Expected ValueError containing {fragment!r}")


@dataclass(frozen=True)
class Execution:
    period: int
    route: str
    vehicle: str
    revision: int
    session: str


@dataclass(frozen=True)
class Sale:
    session: str
    period: int
    route: str
    vehicle: str
    quantity: int


@dataclass
class ContractModel:
    vehicle_qty: dict[str, int] = field(default_factory=lambda: {"A": 100, "B": 60})
    active: Execution | None = None
    revision: int = 0
    next_period: int = 0
    session: str = "S1"
    session_open: bool = True
    closed_and_settled: set[str] = field(default_factory=set)
    postponed_routes: set[str] = field(default_factory=set)
    visits: list[Sale] = field(default_factory=list)
    movements: list[tuple[str, str, int]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    idempotent_commands: dict[str, tuple[tuple, object]] = field(default_factory=dict)

    def resume(self, route: str, vehicle: str):
        if not self.session_open or self.active is not None:
            raise ValueError("session closed or live assignment exists")
        self.revision += 1  # independent monotone fence; never reset on ABA
        self.next_period += 1
        self.active = Execution(self.next_period, route, vehicle, self.revision, self.session)
        self.postponed_routes.discard(route)
        return self.active

    def postpone(self):
        if self.active is None:
            raise ValueError("no active route")
        self.postponed_routes.add(self.active.route)
        self.active = None

    def sell(self, assignment: Execution, quantity: int, request_id: str):
        fingerprint = (assignment, quantity)
        replay = self.idempotent_commands.get(request_id)
        if replay is not None:
            if replay[0] != fingerprint:
                raise ValueError("request_id payload mismatch")
            return replay[1]
        if not self.session_open or assignment != self.active:
            raise ValueError("old execution or vehicle custody fence")
        if quantity <= 0 or self.vehicle_qty[assignment.vehicle] < quantity:
            raise ValueError("invalid vehicle quantity")
        self.vehicle_qty[assignment.vehicle] -= quantity
        self.visits.append(Sale(assignment.session, assignment.period, assignment.route,
                                assignment.vehicle, quantity))
        self.movements.append((assignment.vehicle, "SALE_OUT", -quantity))
        self.idempotent_commands[request_id] = (fingerprint, quantity)
        return quantity

    def end(self):
        if self.active is not None:
            raise ValueError("live route still assigned")
        self.session_open = False

    def count_in_place(self, vehicle: str, actual: int):
        if self.session_open:
            raise ValueError("day must have ended")
        if self.vehicle_qty[vehicle] != actual:
            raise ValueError("variance requires reviewed VEHICLE_RECON")
        self.counts[vehicle] = actual  # evidence only; no stock movements

    def settle(self):
        if self.session_open or set(self.counts) != {"A", "B"}:
            raise ValueError("all required vehicle checkpoints must be sealed")
        self.closed_and_settled.add(self.session)

    def next_day(self):
        if self.session not in self.closed_and_settled:
            raise ValueError("prior session unsettled")
        self.session = "S2"
        self.session_open = True
        self.counts = {}

    def sales_total(self, session: str):
        return sum(sale.quantity for sale in self.visits if sale.session == session)


def _day_one():
    target = ContractModel()
    p1 = target.resume("R1", "A")
    target.sell(p1, 12, "sale-1")
    target.postpone()
    assert "R1" in target.postponed_routes
    p2 = target.resume("R2", "B")
    target.sell(p2, 7, "sale-2")
    target.postpone()
    p3 = target.resume("R1", "A")
    target.sell(p3, 5, "sale-3")
    return target, p1, p2, p3


def test_m00_target_a_b_a_conserves_per_vehicle_custody_and_session_total():
    model, p1, p2, p3 = _day_one()
    assert [p1.period, p2.period, p3.period] == [1, 2, 3]
    assert len({p1.revision, p2.revision, p3.revision}) == 3
    assert p1.route == p3.route == "R1"  # preserved region identity
    assert p2.route == "R2"
    assert model.vehicle_qty == {"A": 83, "B": 53}
    assert model.sales_total("S1") == 24
    assert [(s.period, s.route, s.vehicle, s.quantity) for s in model.visits] == [
        (1, "R1", "A", 12), (2, "R2", "B", 7), (3, "R1", "A", 5)
    ]
    assert len(model.movements) == 3  # exactly the three explicit sales; no status transfer


def test_m00_target_old_a_context_cannot_replay_after_aba():
    model, p1, _, _ = _day_one()
    with expect_value_error("fence"):
        model.sell(p1, 2, "new-stale-sale")
    assert model.vehicle_qty == {"A": 83, "B": 53}
    assert model.sell(p1, 12, "sale-1") == 12  # identical lost-response replay
    with expect_value_error("payload mismatch"):
        model.sell(p1, 11, "sale-1")
    assert model.vehicle_qty == {"A": 83, "B": 53}


def test_m00_target_in_place_count_and_next_day_preserve_physical_stock():
    model, _, _, _ = _day_one()
    model.postpone()
    model.end()
    before_movements = list(model.movements)
    model.count_in_place("A", 83)
    model.count_in_place("B", 53)
    assert model.movements == before_movements
    model.settle()
    model.next_day()
    assert model.session == "S2"
    assert model.sales_total("S1") == 24
    assert model.sales_total("S2") == 0
    assert model.vehicle_qty == {"A": 83, "B": 53}
    p4 = model.resume("R1", "A")
    assert p4.session == "S2" and p4.period == 4
    assert model.vehicle_qty["A"] == 83


def test_m00_target_disallow_unreviewed_variance_and_unsettled_day():
    model, _, _, _ = _day_one()
    model.postpone()
    model.end()
    with expect_value_error("variance"):
        model.count_in_place("A", 80)
    model.count_in_place("A", 83)
    with expect_value_error("checkpoint"):
        model.settle()
    with expect_value_error("unsettled"):
        model.next_day()
    assert model.vehicle_qty["A"] == 83


if __name__ == "__main__":
    tests = (
        test_m00_target_a_b_a_conserves_per_vehicle_custody_and_session_total,
        test_m00_target_old_a_context_cannot_replay_after_aba,
        test_m00_target_in_place_count_and_next_day_preserve_physical_stock,
        test_m00_target_disallow_unreviewed_variance_and_unsettled_day,
    )
    for test in tests:
        test()
    print(f"M00 design contract model: {len(tests)}/{len(tests)} PASS (NOT runtime proof)")
