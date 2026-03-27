from fastapi import APIRouter

from d_presentation.web.routers import line_webhook

router = APIRouter()

router.include_router(line_webhook.router, prefix="/line", tags=["LINE Webhook"])


