from pydantic.dataclasses import dataclass

from a_domain.model.market.quote import Quote


@dataclass(frozen=True)
class SpreadRule:
    tick: float

    def apply(self, bid: Quote, ask: Quote) -> float:
        return (ask.price - bid.price) / self.tick
