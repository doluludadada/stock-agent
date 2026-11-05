from fastapi import APIRouter

from d_presentation.dependencies import KnownHost
from d_presentation.web.routers import account, admin, market, runs, technical_settings, valuation, watchlist, webhook_router

router = APIRouter(prefix="/v1")

router.include_router(runs.router, dependencies=[KnownHost])
router.include_router(watchlist.router, dependencies=[KnownHost])
router.include_router(technical_settings.router, dependencies=[KnownHost])
router.include_router(account.router, dependencies=[KnownHost])
router.include_router(market.router, dependencies=[KnownHost])
router.include_router(valuation.router, dependencies=[KnownHost])
router.include_router(admin.router, dependencies=[KnownHost])
router.include_router(webhook_router.router, prefix="/webhook")
