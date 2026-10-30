from dataclasses import dataclass

from a_domain.model.order.order import Order


@dataclass(frozen=True)
class FreeShippingRule:
    minimum_total: int
    excluded_regions: frozenset[str]

    def apply(self, order: Order, region: str) -> bool:
        if region in self.excluded_regions:
            return False

        return order.total >= self.minimum_total
