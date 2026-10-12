"""Retired current-schema-incompatible historical script: gate_products_p9_rename.

This script depended on the removed legacy Driver authority column and/or the
pre-canonical authentication/authorization contract. It is intentionally not
assigned replacement authority semantics. Use current canonical focused tests
for the subsystem instead.
"""
from __future__ import annotations

import sys

CURRENT_SCHEMA_RETIRED = True
RETIREMENT_REASON = (
    "historical script predates canonical company identity and authorization"
)


def main() -> int:
    print(f"{__file__}: RETIRED - {RETIREMENT_REASON}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
