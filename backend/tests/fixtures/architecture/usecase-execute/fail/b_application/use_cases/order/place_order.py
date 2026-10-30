from a_domain.model.order import Order


class PlaceOrderUseCase:
    def __init__(self, repository: object) -> None:
        self._repository = repository

    async def execute(self, order: Order) -> Order:
        return self._load(order)

    def _load(self, order: Order) -> Order:
        return order

    def summarize(self, order: Order) -> str:
        return str(order)

    def __call__(self, order: Order) -> Order:
        return order


class CancelOrderUseCase:
    async def execute(self, order: Order) -> None:
        return None
