from a_domain.model.market.stock import Stock
from a_domain.rules.trading.exit import BlockedStockRule
from b_application.schemas.pipeline_status import PipelineStatus


class AnalysisCandidates:
    """
    Use Case: Intraday's candidates that go on to analysis, in their order: every one BlockedStockRule does not block,
    so a stock the stop-loss check already sold or whose quote is stale gets no history, news or AI call.
    """

    def __init__(self) -> None:
        self._blocked_rule = BlockedStockRule()

    def execute(self, candidates: list[Stock], status: PipelineStatus) -> list[Stock]:
        sold, stale = status.risk_blocked_stock_ids, status.stale_stock_ids

        return [stock for stock in candidates if self._blocked_rule.apply(stock, sold, stale) is None]
