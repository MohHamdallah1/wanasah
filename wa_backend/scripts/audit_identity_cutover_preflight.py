"""Retired pre-cutover identity audit.

The canonical schema no longer classifies authority from legacy Driver state.
Use audit_identity_phase5_cutover_readiness.py for current-schema readiness.
"""
from __future__ import annotations

import sys

RETIREMENT_REASON = (
    "pre-cutover legacy identity classification is obsolete; "
    "use audit_identity_phase5_cutover_readiness.py"
)


def main() -> int:
    print(f"RETIRED_SCRIPT {__file__}: {RETIREMENT_REASON}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
