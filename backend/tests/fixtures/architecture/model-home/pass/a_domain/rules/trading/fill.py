from pydantic.dataclasses import dataclass

from a_domain.model.market.quote import Quote
from a_domain.model.trading.account import Account
from a_domain.model.trading.order import Fill, Order


@dataclass(frozen=True)
class FillRule:
    fee_rate: float

    def apply(self, order: Order, account: Account, quote: Quote) -> Fill:
        return Fill(quantity=int(account.cash // quote.price), price=quote.price * (1 + self.fee_rate))
