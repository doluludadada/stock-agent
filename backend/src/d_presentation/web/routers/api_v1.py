from fastapi import APIRouter

from d_presentation.web.routers import (
    account,
    admin,
    admin_users,
    auth,
    backtests,
    holdings,
    market,
    rankings,
    runs,
    technical_settings,
    valuation,
    watchlist,
    webhook_router,
)
from d_presentation.web.session import API_PATH, AppRequest, KnownHost

router = APIRouter(prefix=API_PATH)

for module in (
    auth,
    runs,
    watchlist,
    holdings,
    technical_settings,
    account,
    backtests,
    rankings,
    market,
    valuation,
    admin,
    admin_users,
):
    router.include_router(module.router, dependencies=[KnownHost, AppRequest])

router.include_router(webhook_router.router, prefix="/webhook")
