from fastapi import APIRouter

from .credentials import router as credentials_router
from .lifecycle import router as lifecycle_router
from .management import router as management_router
from .read import router as read_router
from .field_roles import router as field_roles_router

router = APIRouter(tags=["Representatives"])
router.include_router(read_router, prefix="/representatives")
router.include_router(management_router, prefix="/representatives")
router.include_router(lifecycle_router, prefix="/representatives")
router.include_router(credentials_router, prefix="/representatives")
router.include_router(field_roles_router, prefix="/representatives")

__all__ = ["router"]
