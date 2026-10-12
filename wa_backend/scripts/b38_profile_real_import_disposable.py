"""Retired disposable B3.8 real-import profiler.

This throwaway milestone fixture encoded the pre-canonical legacy Driver actor
model. It is intentionally retired rather than assigned invented authority.
"""
from __future__ import annotations

import sys

RETIREMENT_REASON = (
    "disposable B3.8 import profiler used the retired legacy Driver authority model"
)


def main() -> int:
    print(f"RETIRED_SCRIPT {__file__}: {RETIREMENT_REASON}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
