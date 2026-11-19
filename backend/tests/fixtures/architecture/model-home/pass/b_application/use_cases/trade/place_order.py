from a_domain.model.trading.order import Order


class PlaceOrder:
    async def execute(self, order: Order) -> Order:
        return order
