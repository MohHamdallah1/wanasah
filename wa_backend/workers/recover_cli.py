# WORKER_RECOVERY_CLI_V1
from __future__ import annotations

import argparse
import asyncio
import json
import selectors
import sys

from workers.recovery import recover_safe_stalled_jobs


async def _recover(mode: str) -> dict[str, int]:
    if mode == "operational":
        from workers.app import STALLED_WORKER_TIMEOUT_SECONDS, app
        from workers.tasks.maintenance import STALLED_RETRY_ALLOWLIST

        allowlist = STALLED_RETRY_ALLOWLIST
        timeout = STALLED_WORKER_TIMEOUT_SECONDS
    elif mode == "product-import":
        from product_import_queue import (
            PRODUCT_IMPORT_STALLED_ALLOWLIST,
            PRODUCT_IMPORT_STALLED_TIMEOUT_SECONDS,
            app,
        )

        allowlist = PRODUCT_IMPORT_STALLED_ALLOWLIST
        timeout = PRODUCT_IMPORT_STALLED_TIMEOUT_SECONDS
    else:
        raise ValueError("unsupported recovery mode")

    async with app.open_async():
        return await recover_safe_stalled_jobs(
            app,
            allowlist=allowlist,
            seconds_since_heartbeat=timeout,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=("operational", "product-import"),
    )
    args = parser.parse_args()

    if sys.platform == "win32":
        result = asyncio.run(
            _recover(args.mode),
            loop_factory=lambda: asyncio.SelectorEventLoop(
                selectors.SelectSelector()
            ),
        )
    else:
        result = asyncio.run(_recover(args.mode))

    print(
        "WORKER_STARTUP_RECOVERY="
        + json.dumps(result, sort_keys=True, separators=(",", ":"))
    )


if __name__ == "__main__":
    main()
