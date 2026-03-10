from fastapi import APIRouter

from d_presentation.web.routers import webhook_router

router = APIRouter(prefix="/v1")

router.include_router(webhook_router.router, prefix="/webhook")


