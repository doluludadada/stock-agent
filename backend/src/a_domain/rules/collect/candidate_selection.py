from dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.types.enums import CandidateSource


@dataclass(frozen=True)
class CandidateSelectionRule:
    """
    Selects one Stock context per stock_id.

    This rule keeps candidate priority out of StockSelector.
    Use cases should load data and call rules, not hide selection rules in helpers.
    """

    def select(
        self,
        held: list[Stock],
        technical: list[Stock],
        buzz: list[Stock],
        manual: list[Stock],
        excluded_stock_ids: set[str] | None = None,
    ) -> list[Stock]:
        excluded = excluded_stock_ids or set()
        selected: dict[str, Stock] = {}

        for stock in technical:
            if stock.stock_id not in excluded:
                selected[stock.stock_id] = stock

        for stock in buzz:
            if stock.stock_id not in excluded:
                selected[stock.stock_id] = stock

        for stock in manual:
            if stock.stock_id not in excluded:
                selected[stock.stock_id] = stock

        for stock in held:
            if stock.stock_id not in excluded:
                stock.source = CandidateSource.HELD_POSITION
                selected[stock.stock_id] = stock

        return list(selected.values())
