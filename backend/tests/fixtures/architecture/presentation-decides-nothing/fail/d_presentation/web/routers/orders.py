from a_domain.rules.shipping import FreeShippingRule
from fastapi import APIRouter

from d_presentation.dependencies import RuntimeDependency

router = APIRouter()


@router.post("/orders/{order_id}/place")
async def place_order(order_id: str, runtime: RuntimeDependency) -> bool:
    minimum_total = runtime.config.shipping.minimum_total
    secret = runtime.config.line.channel_secret
    order = await runtime.pipeline.load_order(order_id, secret)
    return FreeShippingRule(minimum_total=minimum_total).apply(order)
