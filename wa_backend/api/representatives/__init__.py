from fastapi import APIRouter

from .credentials import router as credentials_router
from .lifecycle import router as lifecycle_router
from .management import router as management_router
from .read import router as read_router

router = APIRouter(prefix="/representatives", tags=["Representatives"])
router.include_router(read_router)
router.include_router(management_router)
router.include_router(lifecycle_router)
router.include_router(credentials_router)

__all__ = ["router"]
