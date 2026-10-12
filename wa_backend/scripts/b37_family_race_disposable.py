"""Retired disposable B3.7 family-race gate.

The throwaway milestone gate encoded the pre-canonical legacy Driver actor
model and is intentionally not given replacement authority semantics.
"""
from __future__ import annotations

import sys

RETIREMENT_REASON = (
    "disposable B3.7 race gate used the retired legacy Driver authority model"
)


def main() -> int:
    print(f"RETIRED_SCRIPT {__file__}: {RETIREMENT_REASON}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
