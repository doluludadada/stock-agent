from uuid import UUID

from fastapi import APIRouter, Depends

from b_application.pipeline import Pipeline
from b_application.schemas.pipeline_status import PipelineStatus
from d_presentation.dependencies import get_pipeline

router = APIRouter()


@router.post("/orders/{order_id}/place")
async def place_order(order_id: UUID, region: str, pipeline: Pipeline = Depends(get_pipeline)) -> bool:
    status = await pipeline.place_order(PipelineStatus(order_id=order_id, region=region))
    return status.free_shipping
