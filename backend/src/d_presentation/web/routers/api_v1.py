from fastapi import APIRouter

from d_presentation.web.routers import (
    account,
    admin,
    admin_users,
    auth,
    market,
    runs,
    technical_settings,
    valuation,
    watchlist,
    webhook_router,
)
from d_presentation.web.session import AppRequest, KnownHost

router = APIRouter(prefix="/v1")

for module in (auth, runs, watchlist, technical_settings, account, market, valuation, admin, admin_users):
    router.include_router(module.router, dependencies=[KnownHost, AppRequest])

router.include_router(webhook_router.router, prefix="/webhook")
