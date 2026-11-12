"""Small exact-vehicle review/recount transport adapters."""
from fastapi import APIRouter, Depends

from api.authentication.backoffice_authorization import require_backoffice_capability
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from database import get_db

from .contracts import VarianceApproval, VarianceCount, VarianceRecount
from .http import command_response


def build_variance_router():
    router = APIRouter(prefix="/admin/sessions/{session_id}/inventory-custody/vehicles/{vehicle_id}/variance")
    read, execute = require_backoffice_capability("settlement.read"), require_backoffice_capability("settlement.execute")

    @router.get("")
    async def review(session_id: int, vehicle_id: int, db=Depends(get_db), access=Depends(read),
                     actor=Depends(get_current_backoffice_legacy_driver)):
        async def run():
            from .variance_workflow import read_vehicle_variance
            return await read_vehicle_variance(db, access=access, actor=actor,
                                               session_id=session_id, vehicle_id=vehicle_id)
        return await command_response(db, run)

    @router.get("/count-sheet")
    async def count_sheet(session_id: int, vehicle_id: int, db=Depends(get_db), access=Depends(read),
                          actor=Depends(get_current_backoffice_legacy_driver)):
        async def run():
            from .variance_workflow import read_vehicle_variance
            return await read_vehicle_variance(db, access=access, actor=actor,
                                               session_id=session_id, vehicle_id=vehicle_id, sheet=True)
        return await command_response(db, run)

    @router.post("/approve")
    async def approve(session_id: int, vehicle_id: int, payload: VarianceApproval,
                      db=Depends(get_db), access=Depends(execute), actor=Depends(get_current_backoffice_legacy_driver)):
        async def run():
            from .variance_workflow import run_vehicle_variance
            return await run_vehicle_variance(db, access=access, actor=actor, session_id=session_id,
                                              vehicle_id=vehicle_id, payload=payload, action="approve")
        return await command_response(db, run)

    @router.post("/recount")
    async def recount(session_id: int, vehicle_id: int, payload: VarianceRecount,
                      db=Depends(get_db), access=Depends(execute), actor=Depends(get_current_backoffice_legacy_driver)):
        async def run():
            from .variance_workflow import run_vehicle_variance
            return await run_vehicle_variance(db, access=access, actor=actor, session_id=session_id,
                                              vehicle_id=vehicle_id, payload=payload, action="recount")
        return await command_response(db, run)

    @router.post("/count")
    async def submit_count(session_id: int, vehicle_id: int, payload: VarianceCount,
                           db=Depends(get_db), access=Depends(execute), actor=Depends(get_current_backoffice_legacy_driver)):
        async def run():
            from .variance_workflow import run_vehicle_variance
            return await run_vehicle_variance(db, access=access, actor=actor, session_id=session_id,
                                              vehicle_id=vehicle_id, payload=payload, action="count")
        return await command_response(db, run)

    return router
