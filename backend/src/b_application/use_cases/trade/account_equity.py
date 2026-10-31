from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.trading.valuation import EquityRule, ValuationRule
from b_application.config.app_config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class AccountEquity:
    """
    Use Case: Fixes the run's equity before its first decision: the account's cash plus each position at the latest
    price the run has loaded for it (EquityRule). Every BUY of the run, manual or automatic, takes its risk budget from it.
    """

    def __init__(self, config: AppConfig, logger: ILoggingProvider) -> None:
        self._equity_rule = EquityRule(valuation_rule=ValuationRule(cost_rule=config.market.cost_rule()))
        self._logger = logger

    def execute(self, status: PipelineStatus) -> None:
        status.equity = self._equity_rule.apply(status.account, status.stocks_cache.values())
        self._logger.info(f"Equity fixed for sizing: {status.equity:,.0f}, of which cash {status.account.cash:,.0f}.")
