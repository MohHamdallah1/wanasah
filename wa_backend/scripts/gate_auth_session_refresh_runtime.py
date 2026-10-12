"""Retired runtime legacy auth-session gate.

This standalone gate exercised the pre-canonical Driver login/token transport.
Canonical CompanyPrincipal/session coverage now owns that contract.
"""
from __future__ import annotations

import sys

RETIREMENT_REASON = (
    "legacy Driver auth-session runtime gate was superseded by canonical session coverage"
)


def main() -> int:
    print(f"RETIRED_SCRIPT {__file__}: {RETIREMENT_REASON}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
