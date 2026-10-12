"""Retired source-only legacy auth-session gate.

The gate asserted the pre-canonical Driver token contract. Canonical company
authentication now starts from CompanyPrincipal and explicit access channel.
"""
from __future__ import annotations

import sys

RETIREMENT_REASON = (
    "legacy Driver token source assertions were superseded by canonical auth-session tests"
)


def main() -> int:
    print(f"RETIRED_SCRIPT {__file__}: {RETIREMENT_REASON}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
