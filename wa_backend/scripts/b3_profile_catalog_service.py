"""Retired disposable B3 catalog/price profiler.

This milestone profiler encoded the pre-canonical legacy Driver actor model.
It is intentionally not assigned new authorization semantics.
"""
from __future__ import annotations

import sys

RETIREMENT_REASON = (
    "disposable B3 profiler used the retired legacy Driver authority model"
)


def main() -> int:
    print(f"RETIRED_SCRIPT {__file__}: {RETIREMENT_REASON}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
