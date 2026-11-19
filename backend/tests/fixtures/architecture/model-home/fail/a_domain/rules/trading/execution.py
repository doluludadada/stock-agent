from collections.abc import Sequence

from pydantic.dataclasses import dataclass

from a_domain.model.trading.order import ExchangeOrder, Order


@dataclass(frozen=True)
class BrokerOutcomeRule:
    broker: str

    def apply(self, order: Order, parts: Sequence[ExchangeOrder]) -> bool:
        return sum(part.dealt_shares for part in parts) == order.quantity
