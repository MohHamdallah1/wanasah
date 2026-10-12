"""Retired Stage 8.2.3 uvicorn-layer diagnostic.

This one-off diagnostic minted the pre-canonical legacy company token shape.
Current authentication diagnostics must use canonical CompanyPrincipal/session
transport and should not infer authority from legacy Driver state.
"""
from __future__ import annotations

import sys

RETIREMENT_REASON = (
    "Stage 8.2.3 one-off auth diagnostic predates canonical company identity"
)


def main() -> int:
    print(f"RETIRED_SCRIPT {__file__}: {RETIREMENT_REASON}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
