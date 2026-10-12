"""Retired superseded Live Stock scale-v2 gate.

The maintained current scale path is gate_live_stock_scale.py. This superseded
standalone variant minted the retired legacy Driver token shape and is not
assigned replacement authority semantics.
"""
from __future__ import annotations

import sys

RETIREMENT_REASON = (
    "superseded by gate_live_stock_scale.py and predates canonical company authentication"
)


def main() -> int:
    print(f"RETIRED_SCRIPT {__file__}: {RETIREMENT_REASON}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
