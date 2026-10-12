"""Company HTTP authentication using canonical principal/session boundaries.

Public URLs remain stable. Credential authentication, persisted revalidation,
Dashboard admission, token issuance, rotation and revocation stay in their
existing identity/session modules; this surface only composes their routers.
"""
from fastapi import APIRouter

from api.authentication.login_transport_routes import router as login_router
from api.authentication.logout_routes import router as logout_router
from api.authentication.refresh_routes import router as refresh_router
from api.inventory_permissions import router as inventory_permissions_router


router = APIRouter(tags=["Authentication"])
router.include_router(inventory_permissions_router)
router.include_router(login_router)
router.include_router(refresh_router)
router.include_router(logout_router)


__all__ = ["router"]
