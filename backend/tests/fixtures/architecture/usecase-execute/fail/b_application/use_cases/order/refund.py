from b_application.use_cases import order
from b_application.use_cases.order.place_order import PlaceOrderUseCase
from .place_order import CancelOrderUseCase


class RefundUseCase:
    def __init__(self, place_order: PlaceOrderUseCase, cancel_order: CancelOrderUseCase) -> None:
        self._place_order = place_order
        self._cancel_order = cancel_order

    async def run(self) -> None:
        return None
