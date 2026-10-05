from product_lifecycle import (
    HISTORY,
    INBOUND_COMPLETE,
    INBOUND_NEW,
    RECONCILIATION,
    REPLENISHMENT_NEW,
    RETURN_DISPOSAL,
    ROUTE_LOAD_NEW,
    ROUTE_RETURN,
    ROUTE_SALE_OPEN,
    STOCKTAKE,
    evaluate_product_capability,
)


def test_permanent_stop_blocks_new_commercial_operations():
    for operation in (
        ROUTE_SALE_OPEN,
        ROUTE_LOAD_NEW,
        INBOUND_NEW,
        REPLENISHMENT_NEW,
    ):
        decision = evaluate_product_capability(
            "RETIRING",
            "NONE",
            operation,
        )
        assert decision.allowed is False
        assert decision.code == f"PRODUCT_RETIRING_{operation}_BLOCKED"


def test_permanent_stop_keeps_only_cleanup_and_history_paths():
    for operation in (
        INBOUND_COMPLETE,
        ROUTE_RETURN,
        STOCKTAKE,
        RECONCILIATION,
        RETURN_DISPOSAL,
        HISTORY,
    ):
        decision = evaluate_product_capability(
            "RETIRING",
            "NONE",
            operation,
        )
        assert decision.allowed is True
        assert decision.code == "ALLOWED"
