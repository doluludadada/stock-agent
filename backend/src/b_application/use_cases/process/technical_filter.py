from collections.abc import Sequence

from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.technical.strategy import TechnicalStrategy
from a_domain.rules.trading.decision import DecisionCandidatesRule


class TechnicalFilter:
    """
    Evaluates stocks using a workflow-selected technical strategy: the strategy reads each stock's daily history and
    latest price, calculates its indicators and applies its rules. It returns the stocks that pass, then each stock of `keep`
    that it evaluated and that failed (DecisionCandidatesRule): Intraday keeps its held stocks, so that a position that
    fails the strategy still gets its exit decided.

    The use case applies a strategy but does not decide which strategy
    belongs to Full Cycle, Buzz, Manual, or another workflow.
    """

    def __init__(self, logger: ILoggingProvider) -> None:
        self._candidates_rule = DecisionCandidatesRule()
        self._logger = logger

    def execute(
        self, stocks: list[Stock], strategy: TechnicalStrategy, stats: SystemStats, *, keep: Sequence[Stock] = ()
    ) -> list[Stock]:
        self._logger.info(f"Filtering {len(stocks)} stocks with the selected technical strategy.")
        stats.technical_strategy_id = strategy.strategy_id

        try:
            reports = strategy.apply(stocks)
        except Exception:
            # The one call raised, so each stock is scored alone: a stock whose data the strategy cannot read fails
            # by itself, and every held stock still gets its own report for its exit decision.
            reports = []

            for stock in stocks:
                try:
                    reports.extend(strategy.apply([stock]))
                except Exception as error:
                    self._logger.error(stats.add_error(f"Failed to process market data for {stock.stock_id}: {error}"))
                    reports.append(TechnicalReport(score=0, hard_failures=["Technical indicators unavailable"]))

        for stock, report in zip(stocks, reports, strict=True):
            stock.technical_report = report

        survivors = [stock for stock, report in zip(stocks, reports, strict=True) if report.passed]
        rejected_count = len(stocks) - len(survivors)
        stats.passed_technical += len(survivors)

        self._logger.info(f"Technical filtering completed. Passed={len(survivors)}, Rejected={rejected_count}.")

        return self._candidates_rule.apply(stocks, survivors, keep)
