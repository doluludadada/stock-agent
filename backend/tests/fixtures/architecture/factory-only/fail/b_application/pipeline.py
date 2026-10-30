from b_application.use_cases.order.place_order import PlaceOrderUseCase


class Pipeline:
    def __init__(self, repository: object) -> None:
        self._place_order = PlaceOrderUseCase(repository)
