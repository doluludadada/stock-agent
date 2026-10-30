from ...c_infrastructure.cache import PriceCache
from ..model.order import Order


class DiscountRule:
    def apply(self, order: Order) -> bool:
        return order.total > 0
