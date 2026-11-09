"""Protect Shop financial truth from legacy metadata-edit payloads.

The Dispatch Shop-detail endpoint is NOT a Finance adjustment authority. It may
accept unchanged legacy form snapshots for metadata compatibility, but a stale
or intentionally different monetary value must fail closed. Actual Finance
adjustment authorization, immutable ledger and operation id remain Owner/D03.
"""
from __future__ import annotations

from decimal import Decimal


class ShopFinancialEditConflict(Exception):
    """The requested operation needs an explicit Finance-authorized contract."""

    def __init__(self, *, fields: tuple[str, ...], stale: bool) -> None:
        self.fields = fields
        self.stale = stale
        super().__init__("Shop metadata cannot change receivable or credit cap")


def require_metadata_only_shop_finance(
    *,
    current_balance: Decimal,
    current_credit_cap: Decimal,
    submitted_balance: Decimal | None,
    submitted_credit_cap: Decimal | None,
    includes_metadata: bool,
) -> None:
    """Validate monetary snapshots on an already row-locked tenant Shop.

    This function NEVER modifies Shop, audits, ledgers or inventory. If an old
    client includes money with its metadata form, the values must match the
    locked, persisted amounts exactly. A finance-only PUT is never silently
    acknowledged, even when its submitted amount is already current.
    """
    money_present = submitted_balance is not None or submitted_credit_cap is not None
    if not money_present:
        return

    conflicts = tuple(
        field
        for field, supplied, persisted in (
            ("initialDebt", submitted_balance, current_balance),
            ("maxDebtLimit", submitted_credit_cap, current_credit_cap),
        )
        if supplied is not None and supplied != persisted
    )
    if conflicts:
        raise ShopFinancialEditConflict(fields=conflicts, stale=True)

    if not includes_metadata:
        raise ShopFinancialEditConflict(
            fields=tuple(
                name
                for name, value in (
                    ("initialDebt", submitted_balance),
                    ("maxDebtLimit", submitted_credit_cap),
                )
                if value is not None
            ),
            stale=False,
        )
