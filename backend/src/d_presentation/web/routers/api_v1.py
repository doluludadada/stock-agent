from fastapi import APIRouter

from d_presentation.web.routers import account, runs, technical_settings, watchlist, webhook_router

router = APIRouter(prefix="/v1")

router.include_router(runs.router)
router.include_router(watchlist.router)
router.include_router(technical_settings.router)
router.include_router(account.router)
router.include_router(webhook_router.router, prefix="/webhook")
