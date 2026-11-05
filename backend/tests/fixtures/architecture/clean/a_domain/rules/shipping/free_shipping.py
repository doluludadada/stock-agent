from typing import Annotated

from pydantic import Field
from pydantic.dataclasses import dataclass

from a_domain.model.order.order import Order


@dataclass(frozen=True)
class FreeShippingRule:
    minimum_total: Annotated[int, Field(ge=0)]
    excluded_regions: frozenset[str]

    def apply(self, order: Order, region: str) -> bool:
        if region in self.excluded_regions:
            return False

        return order.total >= self.minimum_total
