from uuid import UUID

from fastapi import APIRouter, Depends

from b_application.pipeline import Pipeline
from d_presentation.dependencies import get_pipeline

router = APIRouter()


@router.post("/orders/{order_id}/place")
async def place_order(order_id: UUID, region: str, pipeline: Pipeline = Depends(get_pipeline)) -> bool:
    status = await pipeline.checkout(order_id, region)
    return status.free_shipping
