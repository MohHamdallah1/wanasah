"""Fresh-process regression: ORM initialization must precede worker readiness."""
from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import event, select
from sqlalchemy.orm import Mapper

import main
from models import Base, Driver


async def run() -> None:
    assert any(not mapper.configured for mapper in Base.registry.mappers)
    configurations = []

    def configuring():
        configurations.append(True)

    async def warm():
        assert all(mapper.configured for mapper in Base.registry.mappers)
        assert configurations == [True]

    @asynccontextmanager
    async def queue():
        yield

    event.listen(Mapper, "before_configured", configuring)
    try:
        with (
            patch.object(main, "warm_database_pool", side_effect=warm) as warmed,
            patch.object(main.product_import_app, "open_async", queue),
            patch.object(main.worker_event_relay, "start", new_callable=AsyncMock),
            patch.object(main.worker_event_relay, "stop", new_callable=AsyncMock),
        ):
            async with main.lifespan(main.app):
                # The first authenticated ORM select must not configure models.
                select(Driver).compile(dialect=main.engine.sync_engine.dialect)
                assert configurations == [True]
            warmed.assert_awaited_once()
    finally:
        event.remove(Mapper, "before_configured", configuring)
    print("STAGE823_MAPPER_STARTUP_GATE=PASS")


if __name__ == "__main__":
    asyncio.run(run())
