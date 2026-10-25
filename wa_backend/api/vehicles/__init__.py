from fastapi import APIRouter

from .lifecycle import router as lifecycle_router
from .load import router as load_router
from .management import router as management_router
from .read import router as read_router

router = APIRouter(tags=["Vehicles"])
router.include_router(read_router, prefix="/vehicles")
router.include_router(management_router, prefix="/vehicles")
router.include_router(lifecycle_router, prefix="/vehicles")
router.include_router(load_router, prefix="/vehicles")

__all__ = ["router"]
